"""Shared type aliases for the mortgage servicing rights transfer test suite."""

from typing import Any, Dict, List, Optional, Tuple

import requests

# A JSON object as carried inside the response envelope's `data` member.
JsonDict = Dict[str, Any]

# A list of JSON objects, as returned by a collection endpoint.
JsonList = List[JsonDict]

# A raw HTTP response; every ApiClient method returns one.
ApiResponse = requests.Response

# Auth headers (X-User-ID / X-User-Role / Content-Type).
Headers = Dict[str, str]

# Query parameters for a collection endpoint.
Params = Optional[Dict[str, Any]]

# (rows, meta) pair returned by validate_paginated.
PaginatedResult = Tuple[JsonList, JsonDict]
