"""
Generic response envelope validators.

These validate the standard API response envelope format:
  Success: { meta: {...}, response_type: "object"|"array", data: ... }
  Error:   { meta: {...}, response_type: "error", data: { error_id, message } }

The error validator supports cross-checking error_id against an HTTP status mapping.
Pass the mapping via set_error_http_status_map() once at import time.
"""

from typing import Dict, List, Optional

import requests

# Module-level error_id → HTTP status mapping.
# Set by the domain-specific error catalog at import time.
_error_http_status_map: Dict[str, int] = {}


def set_error_http_status_map(mapping: Dict[str, int]) -> None:
    """Register the error_id → HTTP status mapping from the domain's error catalog."""
    global _error_http_status_map
    _error_http_status_map = mapping


def validate_success(response: requests.Response, expected_status: int = 200) -> dict:
    """
    Validate success response envelope.
    Checks: status code, envelope shape (meta + response_type + data).
    Returns the 'data' payload for further assertions.
    """
    assert response.status_code == expected_status, (
        f"Expected {expected_status}, got {response.status_code}: {response.text}"
    )
    body = response.json()

    assert "meta" in body, "Missing 'meta' in response envelope"
    assert "response_type" in body, "Missing 'response_type'"
    assert "data" in body, "Missing 'data'"

    meta = body["meta"]
    assert isinstance(meta.get("api_request_id"), str), "meta.api_request_id must be string"
    assert isinstance(meta.get("api_request_timestamp"), str), "meta.api_request_timestamp must be string"

    assert body["response_type"] in ("object", "array"), (
        f"Expected response_type 'object' or 'array', got '{body['response_type']}'"
    )

    return body["data"]


def validate_error(
    response: requests.Response,
    expected_error_id: str,
    expected_status: Optional[int] = None,
) -> dict:
    """
    Validate error response envelope.
    Checks: envelope shape, response_type == 'error', error_id match.
    Cross-checks error_id against HTTP status mapping if available.
    """
    body = response.json()

    assert body.get("response_type") == "error", (
        f"Expected response_type 'error', got '{body.get('response_type')}'"
    )
    assert "data" in body, "Missing 'data' in error envelope"

    error_data = body["data"]
    assert isinstance(error_data.get("error_id"), str), "data.error_id must be string"
    assert isinstance(error_data.get("message"), str), "data.message must be string"
    assert len(error_data["message"].strip()) > 0, "data.message must be non-empty"

    actual_error_id = error_data["error_id"]
    assert actual_error_id == expected_error_id, (
        f"Expected error_id '{expected_error_id}', got '{actual_error_id}'"
    )

    # HTTP status cross-check
    if expected_status:
        assert response.status_code == expected_status, (
            f"Expected HTTP {expected_status} for '{actual_error_id}', "
            f"got {response.status_code}"
        )
    elif actual_error_id in _error_http_status_map:
        expected_http = _error_http_status_map[actual_error_id]
        assert response.status_code == expected_http, (
            f"Error '{actual_error_id}' should return HTTP {expected_http}, "
            f"got {response.status_code}"
        )

    return error_data


def validate_error_is_one_of(
    response: requests.Response,
    acceptable_error_ids: List[str],
) -> str:
    """
    For race condition tests where multiple error outcomes are valid.
    Returns the actual error_id.
    """
    body = response.json()
    assert body.get("response_type") == "error"
    actual = body["data"]["error_id"]
    assert actual in acceptable_error_ids, (
        f"Expected one of {acceptable_error_ids}, got '{actual}'"
    )
    return actual


def validate_paginated(response: requests.Response) -> tuple:
    """
    Validate paginated list response.
    Returns (data_list, meta_dict).
    """
    assert response.status_code == 200, (
        f"Expected 200 for paginated response, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "data" in body, "Missing 'data'"
    assert "meta" in body, "Missing 'meta'"

    meta = body["meta"]
    assert isinstance(meta.get("total_count"), int), "meta.total_count must be int"
    assert isinstance(meta.get("has_more"), bool), "meta.has_more must be bool"
    assert isinstance(meta.get("limit"), int), "meta.limit must be int"
    assert meta["limit"] > 0, "meta.limit must be positive"
    assert isinstance(meta.get("offset"), int), "meta.offset must be int"
    assert meta["offset"] >= 0, "meta.offset must be non-negative"

    return body["data"], meta


def get_success_data(response: requests.Response,
                     expected_status: Optional[int] = None) -> dict:
    """
    Lenient validator for setup steps — accepts any 2xx status.
    Use in fixtures.py for setup calls where the exact status code
    doesn't matter, but clear error messages on failure do.

    When expected_status is given, the response must carry exactly that
    (2xx) status; otherwise any 2xx is accepted.
    """
    if not (200 <= response.status_code < 300):
        body = response.json() if response.text else {}
        error_info = ""
        if body.get("response_type") == "error" and "data" in body:
            err = body["data"]
            error_info = f": {err.get('error_id', '?')} - {err.get('message', '?')}"
        raise AssertionError(
            f"Setup step failed with HTTP {response.status_code}{error_info}"
        )
    if expected_status is not None:
        assert response.status_code == expected_status, (
            f"Expected {expected_status}, got {response.status_code}: "
            f"{response.text}"
        )
    return validate_success(response, response.status_code)
