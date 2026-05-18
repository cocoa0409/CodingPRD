"""Authentication, response envelope, pagination, existence, RBAC.

Covers PRD §2.1 (auth headers, role recognition, ownership), §2.2
(envelope), §2.3 (pagination), §2.6 (nested validation / existence).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    build_user_headers,
    create_applicant,
    create_applicant_payload,
    create_draft_application,
    is_iso8601_timestamp,
    make_applicant_headers,
    setup_filed_application,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# Authentication headers (PRD §2.1)
# ===========================================================================
class TestAuthHeaders:

    def test_missing_both_headers_rejected_with_unauthenticated(self, api):
        """PRD §2.1: "Absence of either header causes the request to be
        rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Claim: a non-trivial endpoint called with no auth headers
        returns ERR_UNAUTHENTICATED.
        """
        res = api.create_applicant(create_applicant_payload(), headers={})
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Absence of either header causes the request to be
        rejected with ERR_UNAUTHENTICATED (HTTP 401)."
        """
        res = api.create_applicant(
            create_applicant_payload(), headers={"X-User-Role": "USPTOAdmin"},
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Absence of either header causes the request to be
        rejected with ERR_UNAUTHENTICATED (HTTP 401)."
        """
        res = api.create_applicant(
            create_applicant_payload(), headers={"X-User-ID": "u1"},
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED.value)

    @pytest.mark.parametrize(
        "bad_role", ["Inventor", "Admin", "applicant", "EXAMINER", "Lawyer"],
    )
    def test_unrecognized_role_rejected_with_forbidden(self, api, bad_role):
        """PRD §2.1: "A request whose X-User-Role is not exactly one of
        Applicant, Examiner, or USPTOAdmin, or whose role is not
        authorised for the requested operation per the endpoint table
        in §4, is rejected with ERR_FORBIDDEN (HTTP 403)."

        Claim: roles outside {Applicant, Examiner, USPTOAdmin} yield
        ERR_FORBIDDEN.
        """
        headers = {"X-User-ID": "u1", "X-User-Role": bad_role}
        res = api.create_applicant(create_applicant_payload(), headers=headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# RBAC (PRD §2.1 + §4)
# ===========================================================================
class TestRBAC:

    def test_create_applicant_forbidden_for_applicant(
        self, api, applicant_fallback_headers,
    ):
        """PRD §2.1: "An Applicant may not invoke any examination action
        and may not perform any administrative action."

        Claim: Applicant role is not authorized to POST /applicants
        (administrative action) and receives ERR_FORBIDDEN.
        """
        res = api.create_applicant(create_applicant_payload(), applicant_fallback_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_create_applicant_forbidden_for_examiner(
        self, api, examiner_headers,
    ):
        """PRD §2.1: "A USPTOAdmin ... owns applicant CRUD and clock
        advancement and reads any resource; the admin cannot perform
        any examiner action and cannot perform applicant write actions
        on applications — this segregation of duties is enforced
        unconditionally."

        Claim: applicant CRUD is reserved to USPTOAdmin per §2.1
        (segregation of duties); Examiner attempting it is forbidden.
        """
        res = api.create_applicant(create_applicant_payload(), examiner_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_clock_advance_forbidden_for_applicant(
        self, api, applicant_fallback_headers,
    ):
        """PRD §2.1: "A USPTOAdmin ... owns applicant CRUD and clock
        advancement".

        Claim: clock advancement is USPTOAdmin-exclusive; Applicant
        attempting it returns ERR_FORBIDDEN.
        """
        res = api.advance_clock("2030-01-01T00:00:00.000Z", applicant_fallback_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_clock_advance_forbidden_for_examiner(
        self, api, examiner_headers,
    ):
        """PRD §2.1: "A USPTOAdmin ... owns applicant CRUD and clock
        advancement"."""
        res = api.advance_clock("2030-01-01T00:00:00.000Z", examiner_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_begin_examination_forbidden_for_applicant(self, api):
        """PRD §2.1: "An Applicant may not invoke any examination action".

        Claim: Applicant role is not authorized to begin examination
        even on the application they own — segregation of duties
        applies to all examination actions.
        """
        applicant, app = setup_filed_application()
        res = api.begin_examination(app["id"], make_applicant_headers(applicant["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_file_application_forbidden_for_examiner(self, api, examiner_headers):
        """PRD §2.1: "An Examiner ... may not pay fees on an applicant's
        behalf nor file or abandon an applicant's application."

        Claim: Examiner cannot file an applicant's application
        (segregation of duties).
        """
        applicant = create_applicant(entity_size="SMALL")
        app = create_draft_application(applicant)
        res = api.file_application(app["id"], examiner_headers)
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Ownership for entity-backed Applicant (PRD §2.1)
# ===========================================================================
class TestOwnership:

    def test_applicant_cannot_act_on_another_applicants_application(self, api):
        """PRD §2.1: "every ownership check on an applicant-scoped
        resource (an Application, OfficeAction, MaintenanceFee,
        PCTPhase, FeeTransaction, or Response) compares the resource's
        owning applicant_id to X-User-ID, and a mismatch is also
        reported as ERR_FORBIDDEN."

        Claim: an Applicant calling /applications/{id}/file on an
        Application that belongs to a different applicant receives
        ERR_FORBIDDEN.
        """
        owner = create_applicant(entity_size="SMALL")
        intruder = create_applicant(entity_size="SMALL")
        app = create_draft_application(owner)
        res = api.file_application(app["id"], make_applicant_headers(intruder["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)

    def test_applicant_cannot_create_application_for_other_applicant(self, api):
        """PRD §2.1 + §3.2: "applicant_id (which must equal the acting
        Applicant's id)".

        Claim: POST /applications whose applicant_id differs from
        X-User-ID is rejected with ERR_FORBIDDEN.
        """
        owner = create_applicant(entity_size="SMALL")
        intruder = create_applicant(entity_size="SMALL")
        from test_helpers import create_application_payload
        payload = create_application_payload(
            applicant_id=owner["id"], application_type="UTILITY",
        )
        res = api.create_application(payload, make_applicant_headers(intruder["id"]))
        validate_error(res, ApiErrorId.ERR_FORBIDDEN.value)


# ===========================================================================
# Response envelope (PRD §2.2)
# ===========================================================================
class TestResponseEnvelope:

    def test_success_envelope_shape(self, api, uspto_admin_headers):
        """PRD §2.2: success responses include meta.api_request_id (a
        server-generated unique identifier ... that starts with req_),
        meta.api_request_timestamp (a server-generated ISO 8601 UTC
        timestamp with three fractional digits), response_type, and
        data.
        """
        res = api.create_applicant(create_applicant_payload(), uspto_admin_headers)
        assert res.status_code == 201
        body = res.json()
        assert "meta" in body and "response_type" in body and "data" in body
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_"), (
            "PRD §2.2: api_request_id must start with 'req_'"
        )
        assert is_iso8601_timestamp(meta["api_request_timestamp"])
        assert body["response_type"] == "object"

    def test_error_envelope_shape(self, api):
        """PRD §2.2: error responses include
        meta.api_request_id, meta.api_request_timestamp,
        response_type == "error", and data.error_id + data.message.
        """
        res = api.create_applicant(create_applicant_payload(), headers={})
        body = res.json()
        assert body["response_type"] == "error"
        assert "error_id" in body["data"] and "message" in body["data"]
        assert body["data"]["error_id"] == ApiErrorId.ERR_UNAUTHENTICATED.value
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]


# ===========================================================================
# Pagination defaults (PRD §2.3)
# ===========================================================================
class TestPagination:

    def test_list_applicants_default_pagination(self, api, uspto_admin_headers):
        """PRD §2.3: "The limit parameter defaults to 10 ... The offset
        parameter defaults to 0".

        Claim: list with no params returns at most 10, and meta
        contains limit, offset, total_count, has_more.
        """
        for _ in range(3):
            api.create_applicant(create_applicant_payload(), uspto_admin_headers)
        data, meta = validate_paginated(api.list_applicants(uspto_admin_headers))
        assert "limit" in meta and "offset" in meta
        assert "total_count" in meta and "has_more" in meta
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] >= 3
        assert len(data) <= 10

    def test_list_applicants_custom_limit_has_more(self, api, uspto_admin_headers):
        """PRD §2.3: "has_more is true when offset + limit < total_count."

        Claim: limit=1 with 3 rows returns has_more True.
        """
        for _ in range(3):
            api.create_applicant(create_applicant_payload(), uspto_admin_headers)
        data, meta = validate_paginated(
            api.list_applicants(uspto_admin_headers, params={"limit": 1}),
        )
        assert len(data) == 1
        assert meta["limit"] == 1
        assert meta["has_more"] is True


# ===========================================================================
# Path-parameter existence (PRD §2.6)
# ===========================================================================
class TestExistence:

    def test_get_nonexistent_applicant_returns_not_found(self, api, uspto_admin_headers):
        """PRD §2.6: "validate path segments strictly left to right. The
        outer resource is resolved first; if it does not exist,
        ERR_NOT_FOUND is returned without examining the inner segment."
        """
        res = api.get_applicant(NON_EXISTENT_UUID, uspto_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_application(self, api, uspto_admin_headers):
        """PRD §2.6: ERR_NOT_FOUND for unresolvable path identifier."""
        res = api.get_application(NON_EXISTENT_UUID, uspto_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_office_action(self, api, uspto_admin_headers):
        """PRD §2.6: ERR_NOT_FOUND for unresolvable path identifier."""
        res = api.get_office_action(NON_EXISTENT_UUID, uspto_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_maintenance_fee(self, api, uspto_admin_headers):
        """PRD §2.6: ERR_NOT_FOUND for unresolvable path identifier."""
        res = api.get_maintenance_fee(NON_EXISTENT_UUID, uspto_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_get_nonexistent_pct_phase(self, api, uspto_admin_headers):
        """PRD §2.6: ERR_NOT_FOUND for unresolvable path identifier."""
        res = api.get_pct_phase(NON_EXISTENT_UUID, uspto_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_nested_path_outer_not_found_first(self, api, uspto_admin_headers):
        """PRD §2.6: "The outer resource is resolved first; if it does
        not exist, ERR_NOT_FOUND is returned without examining the
        inner segment."

        Claim: listing /applications/{id}/fees with a non-existent
        application id returns ERR_NOT_FOUND.
        """
        res = api.list_fee_transactions(NON_EXISTENT_UUID, uspto_admin_headers)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)
