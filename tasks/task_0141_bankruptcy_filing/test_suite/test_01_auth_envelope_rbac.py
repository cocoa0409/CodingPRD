"""Authentication, role validation, RBAC, response envelope, pagination,
and NotFound semantics.

Coverage targets (PRD §2.1, §2.2, §2.3, §2.5, §2.6):
- Missing X-User-Role header -> ERR_UNAUTHENTICATED (401).
- Unrecognized X-User-Role -> ERR_UNAUTHENTICATED (401).
- Role recognized but lacks endpoint permission -> ERR_FORBIDDEN (403).
- Path-segment ID does not resolve -> ERR_NOT_FOUND (404), left-to-right.
- Response envelope shape (success / error).
- Pagination parameters limit/offset bounds.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_creditor,
    create_debtor,
    create_case,
    make_debtor_headers,
    setup_filed_case,
    setup_meeting_held_case,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Missing role / unrecognized role — PRD §2.1
# ===========================================================================
class TestAuthMissing:
    """PRD §2.1: 'A request missing the role header, or supplying any
    value outside this enumeration, is rejected with ERR_UNAUTHENTICATED
    (HTTP 401).'"""

    def test_missing_role_header_rejected(self, api):
        """PRD §2.1: "A request missing the role header, or supplying
        any value outside this enumeration, is rejected with
        ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: omitting X-User-Role -> ERR_UNAUTHENTICATED / 401.
        """
        resp = api._request(
            "GET", f"/cases/{NON_EXISTENT_UUID}",
            headers={"X-User-ID": "anything"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request missing the role header, or supplying
        any value outside this enumeration, is rejected with
        ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: omitting all auth headers -> ERR_UNAUTHENTICATED.
        """
        resp = api._request(
            "GET", f"/cases/{NON_EXISTENT_UUID}", headers={},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


class TestAuthInvalidRole:
    """PRD §2.1: a value outside the enumeration of four roles is
    rejected with ERR_UNAUTHENTICATED."""

    @pytest.mark.parametrize(
        "bad_role",
        ["Admin", "User", "Plaintiff", "BankOfficer", "trustee", ""],
    )
    def test_unknown_role_rejected(self, api, bad_role):
        """PRD §2.1: "A request missing the role header, or supplying
        any value outside this enumeration, is rejected with
        ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: any role value outside {Debtor, Trustee, Creditor,
        Judge} -> ERR_UNAUTHENTICATED.
        """
        resp = api._request(
            "GET", f"/cases/{NON_EXISTENT_UUID}",
            headers={"X-User-Role": bad_role, "X-User-ID": "user-1"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


# ===========================================================================
# RBAC forbidden — PRD §2.1
# ===========================================================================
class TestRbacForbidden:
    """PRD §2.1: 'A request whose role is well-formed but not permitted
    for the requested operation under the RBAC matrix is rejected with
    ERR_FORBIDDEN (HTTP 403).'"""

    def test_trustee_cannot_create_debtor(self, api):
        """PRD §4 RBAC: "POST /debtors ... Debtor". PRD §2.1: "A
        request whose role is well-formed but not permitted for the
        requested operation under the RBAC matrix is rejected with
        ERR_FORBIDDEN (HTTP 403)."

        Claim: Trustee role attempting POST /debtors -> ERR_FORBIDDEN.
        """
        resp = api.create_debtor(
            {"full_name": "Test", "household_size": 1,
             "state_code": "TX"},
            TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_judge_cannot_create_case(self, api):
        """PRD §4 RBAC: "POST /cases ... Debtor". PRD §2.1: "A request
        whose role is well-formed but not permitted for the requested
        operation under the RBAC matrix is rejected with ERR_FORBIDDEN
        (HTTP 403)."

        Claim: Judge role attempting POST /cases -> ERR_FORBIDDEN.
        """
        resp = api.create_case(
            {"debtor_id": NON_EXISTENT_UUID,
             "chapter_requested": "CHAPTER_7"},
            TEST_USERS["judge_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_creditor_cannot_run_means_test(self, api):
        """PRD §4 RBAC: "POST /cases/{case_id}/means-test ... Debtor,
        Trustee". PRD §2.1: "A request whose role is well-formed but
        not permitted for the requested operation under the RBAC matrix
        is rejected with ERR_FORBIDDEN (HTTP 403)."

        Claim: Creditor role attempting means-test -> ERR_FORBIDDEN.
        """
        resp = api.run_means_test(
            NON_EXISTENT_UUID, None,
            TEST_USERS["creditor_fallback_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_debtor_cannot_dismiss_case(self, api):
        """PRD §4 RBAC: "POST /cases/{case_id}/dismiss ... Trustee".
        PRD §2.1: "A request whose role is well-formed but not
        permitted for the requested operation under the RBAC matrix is
        rejected with ERR_FORBIDDEN (HTTP 403)."

        Claim: Debtor role attempting dismiss -> ERR_FORBIDDEN.
        """
        resp = api.dismiss_case(
            NON_EXISTENT_UUID, None,
            TEST_USERS["debtor_fallback_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)

    def test_debtor_cannot_discharge_case(self, api):
        """PRD §4 RBAC: "POST /cases/{case_id}/discharge ... Judge".
        PRD §2.1: "A request whose role is well-formed but not
        permitted for the requested operation under the RBAC matrix is
        rejected with ERR_FORBIDDEN (HTTP 403)."

        Claim: Debtor role attempting discharge -> ERR_FORBIDDEN.
        """
        resp = api.discharge_case(
            NON_EXISTENT_UUID, None,
            TEST_USERS["debtor_fallback_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# NotFound — PRD §2.5
# ===========================================================================
class TestNotFound:
    """PRD §2.5: 'the server resolves each path-segment identifier
    left-to-right and rejects the request with ERR_NOT_FOUND against
    the first identifier that does not resolve to an existing row'."""

    def test_get_case_unknown_id(self, api):
        """PRD §2.5: "the server resolves each path-segment identifier
        left-to-right and rejects the request with ERR_NOT_FOUND
        against the first identifier that does not resolve to an
        existing row."

        Claim: GET /cases/{unknown} -> ERR_NOT_FOUND / 404.
        """
        resp = api.get_case(
            NON_EXISTENT_UUID, TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_debtor_unknown_id(self, api):
        """PRD §2.5: "Likewise a creditor_id or debtor_id path
        parameter that does not resolve must produce ERR_NOT_FOUND."

        Claim: GET /debtors/{unknown} -> ERR_NOT_FOUND.
        """
        resp = api.get_debtor(
            NON_EXISTENT_UUID, TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_creditor_unknown_id(self, api):
        """PRD §2.5: "Likewise a creditor_id or debtor_id path
        parameter that does not resolve must produce ERR_NOT_FOUND."

        Claim: GET /creditors/{unknown} -> ERR_NOT_FOUND.
        """
        resp = api.get_creditor(
            NON_EXISTENT_UUID, TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_plan_lookup_against_nonexistent_case_fails_on_case(self, api):
        """PRD §2.5: "A plan lookup against a non-existent case_id
        fails on the case, not the plan."

        Claim: GET /cases/{unknown}/plans/{any} -> ERR_NOT_FOUND
        (failing on the case).
        """
        resp = api.get_plan(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_claim_lookup_against_nonexistent_case_fails_on_case(self, api):
        """PRD §2.5: "A claim lookup against a non-existent case_id
        fails on the case, not the claim."

        Claim: GET /cases/{unknown}/claims/{any} -> ERR_NOT_FOUND.
        """
        resp = api.get_claim(
            NON_EXISTENT_UUID, NON_EXISTENT_UUID,
            TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_cross_scope_plan_id_is_not_found(self, api):
        """PRD §2.5: "Scope is enforced alongside existence: a plan_id
        that exists but belongs to a different Case than the path's
        case_id is treated as not-found for purposes of this request."

        Claim: looking up a real plan id under a different (real) case
        path -> ERR_NOT_FOUND.
        """
        # Build case A in plan-proposed with a real plan.
        from test_helpers import setup_ch13_plan_proposed
        debtor_a, case_a, _mtr, plan_a, _cr, _cl = setup_ch13_plan_proposed()
        # Build an entirely different case B (a fresh draft).
        debtor_b = create_debtor()
        case_b = create_case(
            debtor=debtor_b, chapter_requested="CHAPTER_13",
        )
        # GET /cases/{B}/plans/{plan-of-A}
        resp = api.get_plan(
            case_b["id"], plan_a["id"], TEST_USERS["trustee_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Response envelope — PRD §2.2
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: every response carries `meta` with `api_request_id`
    starting with `req_` and `api_request_timestamp` ISO 8601, plus
    `response_type` and `data`."""

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".

        Claim: POST /debtors success -> {meta:{api_request_id starts
        with req_, api_request_timestamp ISO}, response_type='object',
        data:Debtor}.
        """
        debtor = create_debtor()
        # The raw response is needed to inspect the envelope.
        resp = api.get_debtor(
            debtor["id"], TEST_USERS["trustee_headers"],
        )
        body = resp.json()
        assert "meta" in body, f"missing meta: {body}"
        assert isinstance(body["meta"].get("api_request_id"), str)
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"api_request_id must start with req_, got "
            f"{body['meta']['api_request_id']!r}"
        )
        assert "api_request_timestamp" in body["meta"]
        assert body.get("response_type") in {"object", "array"}
        assert "data" in body

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes)
        follow this standard envelope format".

        Claim: error responses carry meta + response_type='error' +
        data:{error_id, message}.
        """
        resp = api.get_case(
            NON_EXISTENT_UUID, TEST_USERS["trustee_headers"],
        )
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"response_type must be 'error', got "
            f"{body.get('response_type')!r}"
        )
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]
        assert isinstance(body["data"]["message"], str)


# ===========================================================================
# Pagination — PRD §2.3
# ===========================================================================
class TestPagination:
    """PRD §2.3: 'The limit parameter caps the number of items returned
    and defaults to 10 when omitted, with a minimum of 1 and a maximum
    of 100; values outside this range are rejected as malformed.'"""

    def test_default_limit_returned_in_meta(self, api):
        """PRD §2.3: "For every list response, the meta envelope
        carries the four pagination fields limit, offset, total_count,
        and has_more".

        Claim: a list response's meta carries limit, offset,
        total_count, has_more.
        """
        debtor, case, _mtr = setup_filed_case()
        resp = api.list_collection_actions(
            case["id"], TEST_USERS["trustee_headers"],
        )
        data, meta = validate_paginated(resp)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)

    def test_limit_out_of_range_rejected_too_high(self, api):
        """PRD §2.3: "values outside this range are rejected as
        malformed".

        Claim: limit=101 -> ERR_BAD_REQUEST / 400.
        """
        debtor, case, _mtr = setup_filed_case()
        resp = api.list_collection_actions(
            case["id"], TEST_USERS["trustee_headers"],
            params={"limit": 101},
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_limit_out_of_range_rejected_zero(self, api):
        """PRD §2.3: "values outside this range are rejected as
        malformed".

        Claim: limit=0 -> ERR_BAD_REQUEST / 400.
        """
        debtor, case, _mtr = setup_filed_case()
        resp = api.list_collection_actions(
            case["id"], TEST_USERS["trustee_headers"],
            params={"limit": 0},
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)
