"""Authentication, role validation, response envelope, and pagination.

Coverage targets (PRD §2.1, §2.2, §2.3):
- Missing X-User-Role / X-User-ID header -> ERR_AUTH_MISSING (401).
- Unrecognized role -> ERR_AUTH_FORBIDDEN (403).
- Entity-backed role with unknown X-User-ID -> ERR_AUTH_IDENTITY_UNKNOWN (403).
- Pagination parameters limit/offset bounds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    api_client,
    create_account,
    create_client,
    make_client_user_headers,
    setup_active_client_with_account,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing headers — PRD §2.1
# ===========================================================================
class TestAuthMissing:

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: X-User-ID
        and X-User-Role. Either header missing or malformed yields
        ERR_AUTH_MISSING with HTTP 401."

        Claim: omitting both auth headers -> ERR_AUTH_MISSING / 401.
        """
        resp = api._request("GET", "/model-portfolios", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: X-User-ID
        and X-User-Role. Either header missing or malformed yields
        ERR_AUTH_MISSING with HTTP 401."

        Claim: missing X-User-Role -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/model-portfolios",
            headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two headers: X-User-ID
        and X-User-Role. Either header missing or malformed yields
        ERR_AUTH_MISSING with HTTP 401."

        Claim: missing X-User-ID -> ERR_AUTH_MISSING.
        """
        resp = api._request(
            "GET", "/model-portfolios",
            headers={"X-User-Role": "Advisor"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING.value)


# ===========================================================================
# Unrecognized role — PRD §2.1
# ===========================================================================
class TestAuthForbidden:

    @pytest.mark.parametrize(
        "bad_role",
        ["Admin", "User", "Operator", "Anyone"],
    )
    def test_unrecognized_role_rejected(self, api, bad_role):
        """PRD §2.1: "If the role string is present but is not one of
        the recognised role names, or if the role exists but lacks
        permission for the requested operation per the §1.7 matrix in
        this document and §4 below, the response is
        ERR_AUTH_FORBIDDEN with HTTP 403."

        Claim: unrecognized X-User-Role -> ERR_AUTH_FORBIDDEN / 403.
        """
        resp = api._request(
            "GET", "/model-portfolios",
            headers={"X-User-Role": bad_role, "X-User-ID": "x"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_FORBIDDEN.value)

    def test_role_lacks_permission_rejected(self, api):
        """PRD §2.1: "If the role string is present but is not one of
        the recognised role names, or if the role exists but lacks
        permission for the requested operation per the §1.7 matrix in
        this document and §4 below, the response is
        ERR_AUTH_FORBIDDEN with HTTP 403."

        Claim: TaxAdmin attempting POST /securities (Advisor-only) ->
        ERR_AUTH_FORBIDDEN. (PRD §4 row: POST /securities is
        Advisor-only.)
        """
        resp = api._request(
            "POST", "/securities",
            payload={
                "ticker": "AAA",
                "asset_class": "US_EQUITY",
                "substantially_identical_group_id": "g",
                "last_price_cents": 10000,
            },
            headers=TEST_USERS["tax_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_FORBIDDEN.value)


# ===========================================================================
# Identity unknown — PRD §2.1
# ===========================================================================
class TestAuthIdentityUnknown:

    def test_clientuser_with_unknown_id_rejected(self, api):
        """PRD §2.1: "Entity-backed roles whose X-User-ID does not
        resolve to an actual stored backing entity instance receive
        ERR_AUTH_IDENTITY_UNKNOWN, also 403."

        Claim: ClientUser headers carrying an X-User-ID that does not
        resolve to any Client -> ERR_AUTH_IDENTITY_UNKNOWN.
        """
        # Use a syntactically plausible but non-existent client id.
        bogus = make_client_user_headers(
            "00000000-0000-0000-0000-000000000000",
        )
        client, account = setup_active_client_with_account()
        resp = api.get_account(account["id"], bogus)
        validate_error(
            resp, ApiErrorId.ERR_AUTH_IDENTITY_UNKNOWN.value,
        )


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body" with keys meta, response_type, and data; meta
        carries api_request_id (starts with req_) and
        api_request_timestamp (ISO 8601 UTC with three fractional
        digits).

        Claim: a 200/201 response carries meta with api_request_id
        starting with 'req_' and a 'data' field.
        """
        client = create_client()
        # Use the raw client to read response shape — create_client
        # already validated, but we re-fetch via /clients/{id}.
        resp = api.get_client(
            client["id"], TEST_USERS["compliance_officer_headers"],
        )
        body = resp.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_")

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes)
        follow this standard envelope format" with response_type ==
        'error' and data containing error_id and message.

        Claim: a 4xx response has response_type='error' and data
        carries error_id + message.
        """
        # 401 path — easy to trigger.
        resp = api._request("GET", "/model-portfolios", headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_list_default_pagination_envelope(self, api):
        """PRD §2.3: "The meta envelope on list responses exposes
        limit, offset, total_count (the unpaginated total), and
        has_more (true when more rows remain after this page)."

        Claim: list response meta carries limit, offset, total_count,
        has_more.
        """
        resp = api.list_model_portfolios(
            TEST_USERS["advisor_headers"],
        )
        items, meta = validate_paginated(resp)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta

    @pytest.mark.parametrize("bad_limit", [0, -1, 101, 200])
    def test_invalid_limit_rejected(self, api, bad_limit):
        """PRD §2.3: "Any value of limit outside the inclusive range
        one through one hundred, or any negative offset, is rejected
        with ERR_PAGINATION_INVALID (HTTP 422)."

        Claim: limit outside [1, 100] -> ERR_PAGINATION_INVALID.
        """
        resp = api.list_model_portfolios(
            TEST_USERS["advisor_headers"],
            params={"limit": bad_limit},
        )
        validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)

    @pytest.mark.parametrize("bad_offset", [-1, -100])
    def test_negative_offset_rejected(self, api, bad_offset):
        """PRD §2.3: "Any value of limit outside the inclusive range
        one through one hundred, or any negative offset, is rejected
        with ERR_PAGINATION_INVALID (HTTP 422)."

        Claim: negative offset -> ERR_PAGINATION_INVALID.
        """
        resp = api.list_model_portfolios(
            TEST_USERS["advisor_headers"],
            params={"offset": bad_offset},
        )
        validate_error(resp, ApiErrorId.ERR_PAGINATION_INVALID.value)

    def test_max_limit_accepted(self, api):
        """PRD §2.3: "the maximum is 100".

        Claim: limit=100 is accepted.
        """
        resp = api.list_model_portfolios(
            TEST_USERS["advisor_headers"],
            params={"limit": PAGINATION_MAX_LIMIT},
        )
        validate_paginated(resp)
