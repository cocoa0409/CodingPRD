"""Authentication, RBAC role enforcement, and response-envelope contract.

PRD §2.1 — headers + roles; PRD §2.2 — success/error envelopes.
"""

import pytest

from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ADMIN_HEADERS,
    OPS_HEADERS,
    COMPLIANCE_HEADERS,
    PLACEHOLDER_STREAMER_HEADERS,
    ERR_AUTH_REQUIRED,
    ERR_FORBIDDEN,
    create_streamer_payload,
    create_studio_payload,
)


class TestAuthHeadersRequired:
    """PRD §2.1: 'Every request must carry two HTTP headers: X-User-ID,
    identifying the caller, and X-User-Role, naming the caller's role. Either
    header missing yields ERR_AUTH_REQUIRED with HTTP 401.'
    """

    def test_missing_both_headers_returns_auth_required(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID,
        identifying the caller, and X-User-Role, naming the caller's role.
        Either header missing yields ERR_AUTH_REQUIRED with HTTP 401."
        """
        resp = api.list_streamers(headers={})
        validate_error(resp, ERR_AUTH_REQUIRED, expected_status=401)

    def test_missing_user_id_returns_auth_required(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID,
        identifying the caller, and X-User-Role, naming the caller's role.
        Either header missing yields ERR_AUTH_REQUIRED with HTTP 401."
        """
        resp = api.list_streamers(headers={"X-User-Role": "PlatformAdmin"})
        validate_error(resp, ERR_AUTH_REQUIRED, expected_status=401)

    def test_missing_user_role_returns_auth_required(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers: X-User-ID,
        identifying the caller, and X-User-Role, naming the caller's role.
        Either header missing yields ERR_AUTH_REQUIRED with HTTP 401."
        """
        resp = api.list_streamers(headers={"X-User-ID": "some-id"})
        validate_error(resp, ERR_AUTH_REQUIRED, expected_status=401)


class TestRoleAuthorization:
    """PRD §2.1: 'A header pair whose role is not authorized for the requested
    endpoint yields ERR_FORBIDDEN with HTTP 403.'
    """

    def test_streamer_cannot_create_studio(self, api):
        """PRD §2.1: "A header pair whose role is not authorized for the requested
        endpoint yields ERR_FORBIDDEN with HTTP 403."
        PRD §4: POST /live-schedule/studios is authorized for PlatformAdmin only.
        """
        resp = api.create_studio(create_studio_payload(), PLACEHOLDER_STREAMER_HEADERS)
        validate_error(resp, ERR_FORBIDDEN, expected_status=403)

    def test_ops_reviewer_cannot_create_streamer(self, api):
        """PRD §2.1: "A header pair whose role is not authorized for the requested
        endpoint yields ERR_FORBIDDEN with HTTP 403."
        PRD §4: POST /live-schedule/streamers is authorized for PlatformAdmin only.
        """
        resp = api.create_streamer(create_streamer_payload(), OPS_HEADERS)
        validate_error(resp, ERR_FORBIDDEN, expected_status=403)

    def test_compliance_reviewer_cannot_run_sweep(self, api):
        """PRD §2.1: "A header pair whose role is not authorized for the requested
        endpoint yields ERR_FORBIDDEN with HTTP 403."
        PRD §4: POST /live-schedule/_sweep/run is authorized for PlatformAdmin only.
        """
        resp = api.run_sweep(COMPLIANCE_HEADERS)
        validate_error(resp, ERR_FORBIDDEN, expected_status=403)


class TestResponseEnvelopes:
    """PRD §2.2: standard success and error envelopes."""

    def test_success_envelope_has_meta_response_type_and_data(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body" — keys meta,
        response_type, data.
        """
        resp = api.create_streamer(create_streamer_payload(), ADMIN_HEADERS)
        body = resp.json()
        assert "meta" in body, "success envelope missing 'meta'"
        assert "response_type" in body, "success envelope missing 'response_type'"
        assert "data" in body, "success envelope missing 'data'"
        assert body["response_type"] in ("object", "array")
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id 'starts with req_'"
        )
        assert "api_request_timestamp" in body["meta"]

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: 'data: { "error_id": "UNIQUE_ERROR_IDENTIFIER_STRING",
        "message": "A human-readable explanation of the error." }'.
        """
        resp = api.list_streamers(headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


class TestPaginationDefaults:
    """PRD §2.3: pagination."""

    def test_list_streamers_carries_pagination_meta(self, api):
        """PRD §2.3: "The meta block of a list response carries limit, offset,
        total_count, and has_more, where total_count is the total number of
        items matching the filter (before pagination is applied) and has_more is
        true exactly when offset + len(returned items) < total_count."
        """
        resp = api.list_streamers(ADMIN_HEADERS)
        data, meta = validate_paginated(resp)
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta
        # has_more must be consistent with returned items
        assert meta["has_more"] == (meta["offset"] + len(data) < meta["total_count"])

    def test_pagination_limit_above_max_rejected(self, api):
        """PRD §2.3: "the minimum limit is 1 and the maximum is 100 ... A value
        outside the allowed range yields ERR_PAGINATION_INVALID with HTTP 400."
        """
        resp = api.list_streamers(ADMIN_HEADERS, params={"limit": 101})
        validate_error(resp, "ERR_PAGINATION_INVALID", expected_status=400)

    def test_pagination_limit_below_min_rejected(self, api):
        """PRD §2.3: "the minimum limit is 1 and the maximum is 100 ... A value
        outside the allowed range yields ERR_PAGINATION_INVALID with HTTP 400."
        """
        resp = api.list_streamers(ADMIN_HEADERS, params={"limit": 0})
        validate_error(resp, "ERR_PAGINATION_INVALID", expected_status=400)

    def test_pagination_negative_offset_rejected(self, api):
        """PRD §2.3: "the minimum offset is 0 ... A value outside the allowed
        range yields ERR_PAGINATION_INVALID with HTTP 400."
        """
        resp = api.list_streamers(ADMIN_HEADERS, params={"offset": -1})
        validate_error(resp, "ERR_PAGINATION_INVALID", expected_status=400)
