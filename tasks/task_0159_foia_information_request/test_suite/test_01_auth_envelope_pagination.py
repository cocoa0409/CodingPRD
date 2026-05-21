"""Auth headers, response envelope, and pagination — PRD §2.1, §2.2, §2.3."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    create_request_payload,
    create_requester,
    create_requester_payload,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Auth header validation — PRD §2.1
# ===========================================================================
class TestAuthHeaders:

    def test_missing_user_id_rejected_with_err_missing_auth(self, api):
        """PRD §2.1: "When either header is missing or empty, the server
        rejects the call with `ERR_MISSING_AUTH` and HTTP 401."

        Claim: a call with X-User-Role set but no X-User-ID fails with
        ERR_MISSING_AUTH at HTTP 401.
        """
        headers = {"X-User-Role": "Officer"}
        resp = api.list_requests(headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_missing_user_role_rejected_with_err_missing_auth(self, api):
        """PRD §2.1: "When either header is missing or empty, the server
        rejects the call with `ERR_MISSING_AUTH` and HTTP 401."

        Claim: a call with X-User-ID set but no X-User-Role fails with
        ERR_MISSING_AUTH at HTTP 401.
        """
        headers = {"X-User-ID": "someone"}
        resp = api.list_requests(headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_empty_user_id_rejected_with_err_missing_auth(self, api):
        """PRD §2.1: "When either header is missing or empty, the server
        rejects the call with `ERR_MISSING_AUTH` and HTTP 401."

        Claim: an empty-string X-User-ID is treated as missing.
        """
        headers = {"X-User-ID": "", "X-User-Role": "Officer"}
        resp = api.list_requests(headers)
        validate_error(resp, ApiErrorId.ERR_MISSING_AUTH.value)

    def test_unknown_role_rejected_with_err_invalid_role(self, api):
        """PRD §2.1: "When `X-User-Role` is present but is not one of the
        five recognised values, the server rejects with `ERR_INVALID_ROLE`
        and HTTP 401."

        Claim: an X-User-Role outside the five recognized values fails
        with ERR_INVALID_ROLE at HTTP 401.
        """
        headers = {"X-User-ID": "u-1", "X-User-Role": "SuperAdmin"}
        resp = api.list_requests(headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_ROLE.value)

    def test_role_forbidden_for_endpoint(self, api):
        """PRD §2.1: "When the headers are well-formed but the role is not
        permitted to invoke the requested endpoint, the server rejects with
        `ERR_FORBIDDEN` and HTTP 403."

        Claim: a Requester invoking POST /foia/responsive-records (an
        Officer-exclusive operation per PRD §4) fails with ERR_FORBIDDEN
        at HTTP 403.
        """
        # Use the placeholder Requester headers — the rule under test is
        # the role gate, not ownership.
        headers = TEST_USERS["requester_headers"]
        payload = {"request_id": "00000000-0000-0000-0000-000000000000",
                   "title": "x", "page_count": 1}
        resp = api.create_responsive_record(payload, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Healthz — PRD §4 (unauthenticated liveness probe)
# ===========================================================================
class TestHealthz:

    def test_healthz_returns_200_with_no_auth(self, api):
        """PRD §4: "Liveness probe (no auth)." and PRD §2.1: "Every request
        to the API (apart from the unauthenticated liveness probe) must
        carry two headers".

        Claim: GET /healthz with no auth headers returns HTTP 200.
        """
        resp = api.healthz()
        assert resp.status_code == 200, (
            f"Expected 200, got {resp.status_code}"
        )


# ===========================================================================
# Standard envelope — PRD §2.2
# ===========================================================================
class TestEnvelope:

    def test_success_envelope_carries_meta_and_response_type(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique
        identifier for the request that starts with `req_`."

        Claim: a successful response carries `meta.api_request_id`
        starting with `req_` and an ISO 8601 `api_request_timestamp`.
        """
        requester = create_requester()
        body = resp = api.get_requester(
            requester["id"], TEST_USERS["officer_headers"],
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["response_type"] == "object"
        meta = payload["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            f"api_request_id should start with 'req_', got "
            f"{meta['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"]), (
            f"api_request_timestamp must be ISO 8601, got "
            f"{meta['api_request_timestamp']!r}"
        )

    def test_error_envelope_carries_error_id_and_message(self, api):
        """PRD §2.2: "The `error_id` is a unique, machine-readable
        string that identifies the specific error. The `message` provides
        a human-readable explanation of what went wrong."

        Claim: an error response includes both `error_id` and `message`
        inside `data`.
        """
        resp = api.list_requests({"X-User-Role": "Officer"})
        assert resp.status_code == 401
        payload = resp.json()
        assert payload["response_type"] == "error"
        assert "error_id" in payload["data"]
        assert "message" in payload["data"]
        assert isinstance(payload["data"]["message"], str)
        assert len(payload["data"]["message"]) > 0


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_default_limit_is_10(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10 when omitted".

        Claim: list response meta.limit == 10 when no `limit` is supplied.
        """
        resp = api.list_requests(TEST_USERS["officer_headers"])
        _data, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION_DEFAULT_LIMIT

    def test_limit_below_min_rejected(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10 when omitted,
        has a minimum of 1, and a maximum of 100; any value outside this
        range yields `ERR_INVALID_INPUT`."

        Claim: limit=0 fails with ERR_INVALID_INPUT.
        """
        resp = api.list_requests(
            TEST_USERS["officer_headers"], params={"limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_limit_above_max_rejected(self, api):
        """PRD §2.3: "The `limit` parameter defaults to 10 when omitted,
        has a minimum of 1, and a maximum of 100; any value outside this
        range yields `ERR_INVALID_INPUT`."

        Claim: limit=101 fails with ERR_INVALID_INPUT.
        """
        resp = api.list_requests(
            TEST_USERS["officer_headers"],
            params={"limit": PAGINATION_MAX_LIMIT + 1},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)

    def test_negative_offset_rejected(self, api):
        """PRD §2.3: "The `offset` parameter defaults to 0 and must be
        at least 0."

        Claim: offset=-1 fails with ERR_INVALID_INPUT.
        """
        resp = api.list_requests(
            TEST_USERS["officer_headers"], params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_INPUT.value)
