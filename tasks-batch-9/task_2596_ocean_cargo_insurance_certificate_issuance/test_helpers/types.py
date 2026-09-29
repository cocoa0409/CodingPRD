"""Shared type aliases for the Ocean Cargo Insurance API test suite."""

from typing import Any, Dict, List, Optional, Tuple

import requests

# A JSON object as returned inside the response envelope's `data` member.
JsonDict = Dict[str, Any]

# A list of JSON objects, as returned by a collection endpoint.
JsonList = List[JsonDict]

# A raw HTTP response, returned by every ApiClient method.
ApiResponse = requests.Response

# Auth headers (X-User-ID / X-User-Role / Content-Type).
Headers = Dict[str, str]

# Query parameters for a collection endpoint.
Params = Optional[Dict[str, Any]]

# (data, meta) pair returned by validate_paginated.
PaginatedResult = Tuple[JsonList, JsonDict]
