"""Auth header rejections and the standard response envelope.

Covers PRD §2.1 (auth) and §2.2 (envelope) — these are the universal
preconditions that every other test implicitly depends on.
"""
from __future__ import annotations
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    create_region_payload,
    validate_error,
    validate_success,
)


class TestAuthHeaders:
    """PRD §2.1: 'Every request must carry two HTTP headers: X-User-ID
    and X-User-Role. If either is missing or malformed, the request is
    rejected with ERR_MISSING_AUTH and HTTP 401.'"""

    def test_missing_both_auth_headers_rejected(self, api):
        """PRD §2.1: 'If either is missing or malformed, the request is
        rejected with ERR_MISSING_AUTH and HTTP 401.'"""
        resp = api._request("POST", "/regions", create_region_payload(), {})
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value, 401)

    def test_missing_user_id_rejected(self, api):
        """PRD §2.1: 'If either is missing or malformed, the request is
        rejected with ERR_MISSING_AUTH and HTTP 401.'"""
        resp = api._request(
            "POST", "/regions", create_region_payload(),
            {"X-User-Role": "Admin"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value, 401)

    def test_missing_user_role_rejected(self, api):
        """PRD §2.1: 'If either is missing or malformed, the request is
        rejected with ERR_MISSING_AUTH and HTTP 401.'"""
        resp = api._request(
            "POST", "/regions", create_region_payload(),
            {"X-User-ID": "admin-001"},
        )
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value, 401)

    def test_unknown_role_rejected(self, api):
        """PRD §2.1: 'if both headers are present but the role is not
        one of the four enumerated roles ... the request is rejected
        with ERR_FORBIDDEN_ROLE and HTTP 403.'"""
        resp = api._request(
            "POST", "/regions", create_region_payload(),
            {"X-User-ID": "u-1", "X-User-Role": "NotARealRole"},
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE.value, 403)


class TestResponseEnvelope:
    """PRD §2.2 envelope conventions on success and error paths."""

    def test_success_envelope_carries_meta_and_data(self, api, admin_headers):
        """PRD §2.2: 'The api_request_id is a server-generated unique
        identifier for the request that starts with req_.'"""
        from test_helpers import create_region
        region = create_region()
        resp = api.get_region(region["id"], admin_headers)
        data = validate_success(resp, expected_status=200)
        body = resp.json()
        assert body["response_type"] == "object", (
            "PRD §2.2: response_type is 'object' for a single resource"
        )
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id starts with req_"
        )
        assert data["id"] == region["id"]

    def test_error_envelope_carries_error_id_and_message(
        self, api, admin_headers,
    ):
        """PRD §2.2: 'The error_id is a unique, machine-readable string
        that identifies the specific error.'"""
        resp = api.get_region(NON_EXISTENT_UUID, admin_headers)
        err = validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value, 404)
        assert isinstance(err.get("message"), str) and err["message"], (
            "PRD §2.2: 'The message provides a human-readable explanation'"
        )
        body = resp.json()
        assert body["response_type"] == "error"
