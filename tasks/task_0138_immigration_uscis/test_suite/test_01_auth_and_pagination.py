"""Authentication, role validation, response envelope, and pagination.

Coverage targets (PRD §2.1, §2.2, §2.3, §2.4):
- Missing X-User-Role / X-User-ID header -> ERR_AUTH_MISSING_HEADERS (401).
- Unrecognized role -> ERR_AUTH_UNKNOWN_ROLE (401).
- Role lacks permission -> ERR_FORBIDDEN (403).
- Pagination parameters limit/offset bounds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    PAGINATION_MAX_LIMIT,
    TEST_USERS,
    api_client,
    seed_all_case_type_configs,
    setup_filed_case,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing headers — PRD §2.1
# ===========================================================================
class TestAuthMissingHeaders:

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request that omits either header — or supplies an
        empty value — is rejected with ERR_AUTH_MISSING_HEADERS (HTTP 401)."

        Claim: omitting both auth headers -> ERR_AUTH_MISSING_HEADERS / 401.
        """
        resp = api._request("GET", "/cases", headers={})
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING_HEADERS.value)

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header — or supplies an
        empty value — is rejected with ERR_AUTH_MISSING_HEADERS (HTTP 401)."

        Claim: missing X-User-Role -> ERR_AUTH_MISSING_HEADERS.
        """
        resp = api._request(
            "GET", "/cases",
            headers={"X-User-ID": "anyone"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING_HEADERS.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header — or supplies an
        empty value — is rejected with ERR_AUTH_MISSING_HEADERS (HTTP 401)."

        Claim: missing X-User-ID -> ERR_AUTH_MISSING_HEADERS.
        """
        resp = api._request(
            "GET", "/cases",
            headers={"X-User-Role": "Officer"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING_HEADERS.value)

    def test_empty_role_value_rejected(self, api):
        """PRD §2.1: "A request that omits either header — or supplies
        an empty value — is rejected with ERR_AUTH_MISSING_HEADERS
        (HTTP 401)."

        Claim: empty-string X-User-Role -> ERR_AUTH_MISSING_HEADERS.
        """
        resp = api._request(
            "GET", "/cases",
            headers={"X-User-Role": "", "X-User-ID": "x"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_MISSING_HEADERS.value)


# ===========================================================================
# Unrecognized role — PRD §2.1
# ===========================================================================
class TestAuthUnknownRole:

    @pytest.mark.parametrize(
        "bad_role",
        ["Admin", "User", "Adjudicator", "Anyone"],
    )
    def test_unrecognized_role_rejected(self, api, bad_role):
        """PRD §2.1: "A request whose X-User-Role value does not match
        one of the four defined roles is rejected with
        ERR_AUTH_UNKNOWN_ROLE (HTTP 401)."

        Claim: unrecognized X-User-Role -> ERR_AUTH_UNKNOWN_ROLE / 401.
        """
        resp = api._request(
            "GET", "/cases",
            headers={"X-User-Role": bad_role, "X-User-ID": "x"},
        )
        validate_error(resp, ApiErrorId.ERR_AUTH_UNKNOWN_ROLE.value)


# ===========================================================================
# Role lacks permission — PRD §2.1
# ===========================================================================
class TestAuthForbidden:

    def test_petitioner_cannot_publish_visa_bulletin(self, api):
        """PRD §2.1: "A request whose role is known but is not
        permitted to perform the requested operation, or to act on
        the targeted resource, is rejected with ERR_FORBIDDEN
        (HTTP 403)."

        Claim: a Petitioner attempting a Supervisor-only operation
        (POST /admin/visa-bulletin) -> ERR_FORBIDDEN.
        """
        from test_helpers import make_petitioner_headers
        # Use any non-empty petitioner id — the role check fires
        # before the existence check on the body.
        headers = make_petitioner_headers("any-petitioner-id")
        resp = api._request(
            "POST", "/admin/visa-bulletin",
            payload={
                "bulletin_month": "2026-06",
                "chart_type": "FINAL_ACTION",
                "preference_category": "F2A",
                "country": "MEX",
                "cutoff_date": "CURRENT",
            },
            headers=headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_officer_cannot_advance_clock(self, api, officer_headers):
        """PRD §2.1: "A Supervisor may perform every operation an
        Officer may perform, and additionally configure case types,
        publish visa bulletins, set the chart in effect, and advance
        the test clock."

        Claim: Officer attempting Supervisor-exclusive
        POST /_clock/advance -> ERR_FORBIDDEN.
        """
        resp = api._request(
            "POST", "/_clock/advance",
            payload={"to": "2030-01-01T00:00:00.000Z"},
            headers=officer_headers,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:

    def test_limit_below_minimum_rejected(self, api, officer_headers):
        """PRD §2.3: "A request whose limit falls outside the inclusive
        range 1 to 100, or whose offset is negative, is rejected with
        ERR_INVALID_PAGINATION (HTTP 422)."

        Claim: limit=0 -> ERR_INVALID_PAGINATION.
        """
        resp = api_client.list_cases(officer_headers, params={"limit": 0})
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_limit_above_maximum_rejected(self, api, officer_headers):
        """PRD §2.3: "A request whose limit falls outside the inclusive
        range 1 to 100, or whose offset is negative, is rejected with
        ERR_INVALID_PAGINATION (HTTP 422)."

        Claim: limit=101 -> ERR_INVALID_PAGINATION.
        """
        resp = api_client.list_cases(
            officer_headers, params={"limit": PAGINATION_MAX_LIMIT + 1},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_negative_offset_rejected(self, api, officer_headers):
        """PRD §2.3: "A request whose limit falls outside the inclusive
        range 1 to 100, or whose offset is negative, is rejected with
        ERR_INVALID_PAGINATION (HTTP 422)."

        Claim: offset=-1 -> ERR_INVALID_PAGINATION.
        """
        resp = api_client.list_cases(
            officer_headers, params={"offset": -1},
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_PAGINATION.value)

    def test_limit_one_accepted(self, api, officer_headers):
        """PRD §2.3: "The default limit is 10, the minimum is 1, and
        the maximum is 100."

        Claim: limit=1 boundary is accepted and meta reflects it.
        """
        seed_all_case_type_configs()
        setup_filed_case(case_type="I-130", seed_configs=False)
        setup_filed_case(case_type="I-130", seed_configs=False)
        resp = api_client.list_cases(
            officer_headers, params={"limit": 1, "offset": 0},
        )
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert len(data) <= 1

    def test_limit_one_hundred_accepted(self, api, officer_headers):
        """PRD §2.3: "the maximum is 100".

        Claim: limit=100 boundary is accepted.
        """
        resp = api_client.list_cases(
            officer_headers, params={"limit": PAGINATION_MAX_LIMIT},
        )
        data, meta = validate_paginated(resp)
        assert meta["limit"] == PAGINATION_MAX_LIMIT


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_shape(self, api, supervisor_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".

        Claim: success response has meta.api_request_id,
        api_request_timestamp, response_type, and data fields.
        """
        resp = api_client.get_clock(supervisor_headers)
        body = resp.json()
        assert "meta" in body
        assert "response_type" in body
        assert "data" in body
        assert body["response_type"] in ("object", "array")
        meta = body["meta"]
        assert "api_request_id" in meta
        assert meta["api_request_id"].startswith("req_"), (
            "api_request_id must start with 'req_' per PRD §2.2"
        )
        assert "api_request_timestamp" in meta

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format".

        Claim: error response has response_type='error' and data.error_id
        + data.message.
        """
        resp = api._request("GET", "/cases", headers={})
        body = resp.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"].strip() != ""
