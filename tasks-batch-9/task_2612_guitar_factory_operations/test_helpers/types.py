"""Shared type aliases for the guitar factory helper package."""

from typing import Any, Dict, List, Optional

import requests

JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
Headers = Optional[Dict[str, str]]
Params = Optional[Dict[str, Any]]
ApiResponse = requests.Response
