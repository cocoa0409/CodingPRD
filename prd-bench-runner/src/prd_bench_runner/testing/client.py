"""
Generic API client base class.

Provides the shared HTTP request infrastructure (_request, session management,
URL construction). Subclass this and add one method per API endpoint.

Usage:

    from prd_bench_runner.testing import GenericApiClient

    class ApiClient(GenericApiClient):
        def create_order(self, payload, headers):
            return self._request("POST", "/orders", payload, headers)
        ...
"""

import os
from typing import Any, Dict, Optional

import requests


class GenericApiClient:
    """
    Base HTTP client for API compliance testing.

    Subclass this and add one method per API endpoint.
    Methods should delegate to _request() and return raw requests.Response
    so tests can assert status codes.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.environ.get(
            "API_BASE_URL", "http://localhost:3000"
        )
        self.session = requests.Session()

    def _request(
        self,
        method: str,
        path: str,
        payload: Any = None,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict] = None,
    ) -> requests.Response:
        """
        Send an HTTP request to the API under test.

        - GET/DELETE: payload passed as query params
        - POST/PUT/PATCH: payload passed as JSON body
        - Returns raw requests.Response for status code assertions
        """
        url = f"{self.base_url}{path}"
        kwargs: Dict[str, Any] = {"headers": headers or {}}

        if method.upper() in ("GET", "DELETE"):
            kwargs["params"] = payload or params
        else:
            kwargs["json"] = payload
            if params:
                kwargs["params"] = params

        return self.session.request(method, url, **kwargs)
