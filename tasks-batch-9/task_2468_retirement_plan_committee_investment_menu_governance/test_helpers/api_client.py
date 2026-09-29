"""Thin HTTP layer over the framework's generic client.

The base URL, server lifecycle and database reset are owned by the runner; this
module only translates "call this endpoint as this user" into a request and
gives back the parsed envelope.
"""

from typing import Any, Dict, List, Optional, Tuple

import requests

from prd_bench_local_runner.testing import (
    GenericApiClient,
    build_user_headers,
    get_success_data,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from .constants import DEFAULT_CLOCK
from .types import Headers, JsonDict, Role


class ApiClient:
    """A per-test HTTP client.

    Every method returns the raw ``requests.Response`` so the caller decides
    whether to assert success or a specific ``error_id``.
    """

    def __init__(self, base_url: Optional[str] = None) -> None:
        self._client = GenericApiClient(base_url=base_url)

    # -- raw verbs ---------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._client.base_url

    def get(
        self,
        path: str,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._client._request("GET", path, payload=None, headers=headers, params=params)

    def post(
        self,
        path: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._client._request("POST", path, payload=payload, headers=headers)

    def patch(
        self,
        path: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._client._request("PATCH", path, payload=payload, headers=headers)

    def put(
        self,
        path: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
    ) -> requests.Response:
        return self._client._request("PUT", path, payload=payload, headers=headers)

    def delete(
        self,
        path: str,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        return self._client._request(
            "DELETE", path, payload=None, headers=headers, params=params
        )

    def request(
        self,
        method: str,
        path: str,
        payload: Optional[JsonDict] = None,
        headers: Optional[Headers] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> requests.Response:
        """Send an arbitrary verb — used by tests that deliberately omit the
        identity headers."""
        return self._client._request(
            method, path, payload=payload, headers=headers, params=params
        )

    # -- logical clock -----------------------------------------------------

    def set_clock(self, current_utc: str, headers: Optional[Headers] = None) -> requests.Response:
        """Move the logical clock.  The endpoint is an out-of-band test control,
        so a permitted administrative identity is supplied by default."""
        if headers is None:
            headers = build_user_headers("clock-operator", Role.PLAN_SPONSOR_ADMIN)
        return self.post("/_clock/set_current_utc", {"current_utc": current_utc}, headers)

    def reset_clock(self, headers: Optional[Headers] = None) -> requests.Response:
        return self.set_clock(DEFAULT_CLOCK, headers)


def headers_for(user_id: str, role: str) -> Headers:
    """``X-User-ID`` / ``X-User-Role`` (plus a JSON content type)."""
    return build_user_headers(user_id, role)


def paginate_params(
    limit: Optional[int] = None, offset: Optional[int] = None, **extra: Any
) -> Dict[str, Any]:
    """Build a query string, dropping keys the caller left as ``None`` so the
    server's own defaults apply."""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    for key, value in extra.items():
        if value is not None:
            params[key] = value
    return params


def collect_all(
    client: ApiClient,
    path: str,
    headers: Headers,
    page_size: int = 100,
    **filters: Any,
) -> List[JsonDict]:
    """Walk a paginated collection to exhaustion and return every row."""
    rows: List[JsonDict] = []
    offset = 0
    while True:
        response = client.get(
            path, headers, paginate_params(limit=page_size, offset=offset, **filters)
        )
        data, meta = validate_paginated(response)
        rows.extend(data)
        if not meta["has_more"]:
            return rows
        offset += page_size
        assert offset < 10000, "pagination did not terminate"


__all__ = [
    "ApiClient",
    "headers_for",
    "paginate_params",
    "collect_all",
    "build_user_headers",
    "get_success_data",
    "validate_success",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "Tuple",
]
