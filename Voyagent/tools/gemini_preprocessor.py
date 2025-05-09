import os
import json
import logging
from typing import Dict, Any, Optional, Tuple
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

# Load environment variables
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

class GeminiPreprocessor:
    """
    A preprocessor that uses Gemini to structure natural language travel queries
    into formats that are better suited for various Apify tools.
    """
    
    def __init__(self):
        """Initialize the Gemini preprocessor."""
        api_key = os.getenv("GOOGLE_API_KEY")
        if api_key:
            logger.info(f"Gemini API key loaded: {api_key[:8]}...")
        else:
            logger.error("Failed to load GOOGLE_API_KEY from environment")
            
        self.llm = ChatGoogleGenerativeAI(
            model="gemini-1.5-flash",  # Using the latest Gemini model
            temperature=0,  # Keep it deterministic for structured outputs
            google_api_key=api_key
        )
    
    def preprocess_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Preprocess a natural language query into structured data for tools.
        
        Args:
            query: The original user query
            context: Optional context from previous conversations
            
        Returns:
            A dictionary containing structured data and metadata about the query
        """
        logger.info(f"Preprocessing query with Gemini: {query}")
        
        system_prompt = """You are a travel query analyzer that extracts structured information from natural language travel queries.
        Your job is to parse the query and identify key components like:
        
        1. Query type (flight search, place info, directions, activity recommendations)
        2. Origin location (for travel queries)
        3. Destination location(s)
        4. Date information (exact dates or relative periods like "next week")
        5. Additional preferences or constraints
        
        Format your response as a JSON object with these fields:
        {
            "query_type": "flight" | "poi" | "directions" | "recommendations" | "general" | "transport_comparison",
            "origin": "location name or empty string if not specified",
            "destination": "location name",
            "date_info": {
                "start_date": "YYYY-MM-DD or empty string",
                "end_date": "YYYY-MM-DD or empty string",
                "duration": "number of days or empty string"
            },
            "preferences": ["list", "of", "preferences"],
            "structured_query": "a reformatted version of the query optimized for search tools",
            "transport_modes": ["flight", "drive", "bus", "train"] (only for transport_comparison queries)
        }
        
        If the query is about comparing different transportation methods (like "flights vs driving"), 
        set query_type to "transport_comparison" and list the transport modes in transport_modes array.

        For airport codes, use standard airport codes like SFO for San Francisco or FAT for Fresno.
        
        For example, given "I want to fly to Paris from New York next weekend", you would return:
        {
            "query_type": "flight",
            "origin": "New York",
            "destination": "Paris",
            "date_info": {
                "start_date": "2025-05-10", 
                "end_date": "2025-05-12",
                "duration": "2"
            },
            "preferences": [],
            "structured_query": "flights from New York to Paris departing May 10, 2025"
        }
        
        For "Should I drive or fly from San Francisco to Yosemite?", return:
        {
            "query_type": "transport_comparison",
            "origin": "San Francisco",
            "destination": "Yosemite",
            "date_info": {"start_date": "", "end_date": "", "duration": ""},
            "preferences": [],
            "structured_query": "comparison of driving vs flying from San Francisco to Yosemite",
            "transport_modes": ["drive", "flight"]
        }
        
        Today's date is May 2, 2025. Use this to calculate relative dates.
        For "this weekend", use May 3-4, 2025. For "next weekend", use May 10-11, 2025.
        """
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=query)
        ]
        
        try:
            # Get structured information from Gemini
            result = self.llm.invoke(messages).content
            
            # Extract JSON from the response if needed
            json_start = result.find("{")
            json_end = result.rfind("}") + 1
            if json_start >= 0 and json_end > 0:
                json_str = result[json_start:json_end]
                structured_data = json.loads(json_str)
            else:
                structured_data = {"error": "Could not extract structured data"}
                logger.error(f"Failed to extract JSON from Gemini response: {result}")
                
            logger.info(f"Structured data: {json.dumps(structured_data)}")
            
            # Add original query to the response
            structured_data["original_query"] = query
            
            # Special case handling for comparison queries
            if "vs" in query.lower() or "versus" in query.lower() or "or" in query.lower() and ("fly" in query.lower() or "drive" in query.lower()):
                if structured_data.get("query_type") != "transport_comparison":
                    structured_data["query_type"] = "transport_comparison"
                    structured_data["transport_modes"] = []
                    
                    if "fly" in query.lower() or "flight" in query.lower():
                        structured_data["transport_modes"].append("flight")
                    if "drive" in query.lower() or "car" in query.lower():
                        structured_data["transport_modes"].append("drive")
                    if "train" in query.lower():
                        structured_data["transport_modes"].append("train")
                    if "bus" in query.lower():
                        structured_data["transport_modes"].append("bus")
            
            # Fix airport codes
            if structured_data.get("origin", "").lower() in ["sf", "san francisco"]:
                structured_data["origin_code"] = "SFO"
            elif structured_data.get("origin", "").lower() in ["fresno", "fres"]:
                structured_data["origin_code"] = "FAT"
                
            if structured_data.get("destination", "").lower() in ["fresno", "fres"]:
                structured_data["destination_code"] = "FAT"
            elif structured_data.get("destination", "").lower() in ["sf", "san francisco"]:
                structured_data["destination_code"] = "SFO"
            
            return structured_data
            
        except Exception as e:
            logger.error(f"Error preprocessing query with Gemini: {e}", exc_info=True)
            return {
                "error": str(e),
                "original_query": query,
                "query_type": "general"
            }
        
    def extract_travel_info(self, query: str) -> Tuple[str, str, str]:
        """
        Extract the origin, destination, and dates from a flight query.
        
        Args:
            query: The user's query about flights
            
        Returns:
            A tuple of (origin, destination, date)
        """
        structured = self.preprocess_query(query)
        
        origin = structured.get("origin", "")
        destination = structured.get("destination", "")
        
        date_info = structured.get("date_info", {})
        date = date_info.get("start_date", "")
        
        return origin, destination, date
    
    def get_optimized_query(self, query: str, tool_name: str) -> str:
        """
        Get an optimized version of the query for a specific tool.
        
        Args:
            query: The original user query
            tool_name: The name of the tool to optimize for (e.g., "apify_flight")
            
        Returns:
            An optimized query string
        """
        structured = self.preprocess_query(query)
        
        if "structured_query" in structured:
            return structured["structured_query"]
        
        # Fallback to original query if no structured query is available
        return query