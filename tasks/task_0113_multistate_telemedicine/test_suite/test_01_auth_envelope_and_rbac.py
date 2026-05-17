"""Auth, RBAC, response envelope, pagination, and existence checks.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination), §2.6
(NotFound).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_consult_payload,
    create_patient_payload,
    create_physician_payload,
    create_prescription_payload,
    create_state_license_payload,
    is_iso8601_timestamp,
    make_physician_headers,
    occ_payload,
    route_consult_payload,
    setup_in_progress_consult,
    setup_physician_with_license,
    setup_routed_consult,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected with
        ERR_UNAUTHENTICATED."

        Claim: a POST with neither header set returns
        ERR_UNAUTHENTICATED.
        """
        res = api.create_physician(create_physician_payload(), headers={})
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected with
        ERR_UNAUTHENTICATED."

        Claim: omitting X-User-ID returns ERR_UNAUTHENTICATED.
        """
        res = api.create_physician(
            create_physician_payload(),
            headers={"X-User-Role": "PlatformAdmin"},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "A request that omits either header is rejected with
        ERR_UNAUTHENTICATED."

        Claim: omitting X-User-Role returns ERR_UNAUTHENTICATED.
        """
        res = api.create_physician(
            create_physician_payload(),
            headers={"X-User-ID": "admin-001"},
        )
        validate_error(res, "ERR_UNAUTHENTICATED")


# ===========================================================================
# §2.1 RBAC — wrong role rejected
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "A request whose role is not authorized for the
    endpoint in question is rejected with ERR_FORBIDDEN.\""""

    def test_compliance_officer_cannot_create_physician(self, api):
        """PRD §4: POST /telemed/physicians is exclusive to PlatformAdmin.
        PRD §2.1: "A request whose role is not authorized for the
        endpoint in question is rejected with ERR_FORBIDDEN."

        Claim: a ComplianceOfficer calling POST /telemed/physicians
        returns ERR_FORBIDDEN.
        """
        res = api.create_physician(
            create_physician_payload(),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_physician_cannot_create_patient(self, api):
        """PRD §2.1: "Segregation of duties is enforced at the role
        level: a Physician cannot route, decline, close, or appeal a
        consult, cannot mark a prescription dispensed, and cannot edit
        a Patient record."

        Claim: a Physician calling POST /telemed/patients returns
        ERR_FORBIDDEN.
        """
        res = api.create_patient(
            create_patient_payload(),
            TEST_USERS["physician_fallback_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_compliance_officer_cannot_start_consult(self, api):
        """PRD §2.1: "A ComplianceOfficer cannot start, complete, prescribe, or issue prescriptions."
        PRD §2.1: "A request whose role is not authorized for the endpoint in question is rejected with ERR_FORBIDDEN."

        Claim: a ComplianceOfficer calling start returns ERR_FORBIDDEN.
        """
        _, _, _, consult = setup_routed_consult()
        res = api.start_consult(
            consult["id"], occ_payload(version=consult["version"]),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_physician_cannot_route_consult(self, api):
        """PRD §2.1: "Segregation of duties is enforced at the role
        level: a Physician cannot route, decline, close, or appeal a
        consult, cannot mark a prescription dispensed, and cannot edit
        a Patient record."

        Claim: a Physician calling route returns ERR_FORBIDDEN.
        """
        physician, _ = setup_physician_with_license()
        # Use any consult id; even a non-existent path should hit
        # forbidden first since auth/RBAC (priorities 1-2) precede
        # existence (priority 3).
        res = api.route_consult(
            NON_EXISTENT_UUID,
            route_consult_payload(physician_id=physician["id"]),
            make_physician_headers(physician["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_physician_cannot_mark_dispensed(self, api):
        """PRD §2.1: "Segregation of duties is enforced at the role
        level: a Physician cannot route, decline, close, or appeal a
        consult, cannot mark a prescription dispensed, and cannot edit
        a Patient record."

        Claim: a Physician calling mark-dispensed returns ERR_FORBIDDEN.
        """
        res = api.mark_dispensed_prescription(
            NON_EXISTENT_UUID, occ_payload(),
            TEST_USERS["physician_fallback_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_compliance_officer_cannot_approve_claim(self, api):
        """PRD §2.1: "A request whose role is not authorized for the
        endpoint in question is rejected with ERR_FORBIDDEN."
        PRD §4 (endpoint table): "POST /telemed/claims/{id}/approve ...
        Payer".

        Claim: a ComplianceOfficer calling approve returns
        ERR_FORBIDDEN.
        """
        res = api.approve_claim(
            NON_EXISTENT_UUID, occ_payload(),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_payer_cannot_appeal_claim(self, api):
        """PRD §2.1: "A request whose role is not authorized for the
        endpoint in question is rejected with ERR_FORBIDDEN."
        PRD §4 (endpoint table): "POST /telemed/claims/{id}/appeal ...
        ComplianceOfficer".

        Claim: a Payer calling appeal returns ERR_FORBIDDEN.
        """
        res = api.appeal_claim(
            NON_EXISTENT_UUID, occ_payload(),
            TEST_USERS["payer_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.1 Physician ownership — entity-backed identity check
# ===========================================================================
class TestPhysicianOwnership:
    """PRD §2.1 (Physician role): "Ownership checks on any resource that
    references a Physician — most importantly the physician_id on a
    Consult and the prescribing_physician_id on a Prescription — compare
    the resource's foreign-key field to X-User-ID, and a mismatch is
    rejected with ERR_FORBIDDEN.\""""

    def test_different_physician_cannot_start_consult(self, api):
        """PRD §2.1: "Ownership checks on any resource that references a
        Physician — most importantly the physician_id on a Consult ...
        compare the resource's foreign-key field to X-User-ID, and a
        mismatch is rejected with ERR_FORBIDDEN."

        Claim: physician_b (different id) attempting to /start a consult
        routed to physician_a returns ERR_FORBIDDEN.
        """
        from test_helpers import setup_two_physicians_one_consult
        _, physician_b, _, consult_in_prog = (
            setup_two_physicians_one_consult()
        )
        # Roll back to ROUTED: we need a ROUTED consult that physician_b
        # tries to /start. Easier: use a fresh setup that returns ROUTED
        # consult assigned to physician_a.
        _, _, _, consult = setup_routed_consult()
        # Different physician calls /start — id mismatch → ERR_FORBIDDEN.
        from test_helpers import create_physician
        other = create_physician()
        res = api.start_consult(
            consult["id"], occ_payload(version=consult["version"]),
            make_physician_headers(other["id"]),
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response Envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: success and error envelope shape."""

    def test_success_envelope_shape(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body".
        PRD §2.2: "The api_request_id is a server-generated unique
        identifier for the request that starts with req_."

        Claim: a successful physician creation returns the standard
        envelope.
        """
        res = api.create_physician(
            create_physician_payload(),
            TEST_USERS["admin_headers"],
        )
        body = res.json()
        assert "meta" in body and "data" in body
        assert "api_request_id" in body["meta"]
        assert body["meta"]["api_request_id"].startswith("req_"), (
            f"PRD §2.2 requires api_request_id to start with 'req_', "
            f"got {body['meta']['api_request_id']!r}"
        )
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] in ("object", "array")
        # response_type is 'object' for a single resource.
        assert body["response_type"] == "object"

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format".
        PRD §2.2: "The error_id is a unique, machine-readable string
        that identifies the specific error."

        Claim: an unauthenticated request returns the standard error
        envelope.
        """
        res = api.create_physician(create_physician_payload(), headers={})
        body = res.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == "ERR_UNAUTHENTICATED"
        assert isinstance(body["data"]["message"], str)
        assert "api_request_id" in body["meta"]


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: limit ∈ [1,100], offset ≥ 0; otherwise
    ERR_PAGINATION_INVALID."""

    @pytest.mark.parametrize("limit", [0, -1, 101, 200])
    def test_invalid_limit_rejected(self, api, limit):
        """PRD §2.3: "The limit parameter defaults to 10 when omitted,
        must be at least 1, and must not exceed 100 ... Any request that
        violates these bounds is rejected with ERR_PAGINATION_INVALID."

        Claim: limit outside [1, 100] returns ERR_PAGINATION_INVALID.
        """
        res = api.list_physicians(
            TEST_USERS["admin_headers"],
            params={"limit": limit, "offset": 0},
        )
        validate_error(res, "ERR_PAGINATION_INVALID")

    def test_negative_offset_rejected(self, api):
        """PRD §2.3: "the offset parameter defaults to 0 when omitted
        and must be a non-negative integer."

        Claim: a negative offset returns ERR_PAGINATION_INVALID.
        """
        res = api.list_physicians(
            TEST_USERS["admin_headers"],
            params={"limit": 10, "offset": -1},
        )
        validate_error(res, "ERR_PAGINATION_INVALID")

    def test_valid_pagination_returns_envelope(self, api):
        """PRD §2.3: "the response's meta block echoes limit, offset,
        the unfiltered total_count matching the query, and a boolean
        has_more".

        Claim: a list call with valid params returns the paginated
        envelope.
        """
        # Ensure at least one physician exists.
        setup_physician_with_license()
        res = api.list_physicians(
            TEST_USERS["admin_headers"],
            params={"limit": 10, "offset": 0},
        )
        data, meta = validate_paginated(res)
        assert isinstance(data, list)
        assert isinstance(meta["total_count"], int)
        assert isinstance(meta["has_more"], bool)
        assert meta["limit"] == 10
        assert meta["offset"] == 0


# ===========================================================================
# §2.6 Existence — ERR_NOT_FOUND
# ===========================================================================
class TestNotFound:
    """PRD §2.6: "existence of all path-referenced resources, evaluated
    left-to-right through the URL hierarchy (any miss → ERR_NOT_FOUND)."
    """

    def test_get_nonexistent_physician(self, api):
        """PRD §2.6: "existence of all path-referenced resources,
        evaluated left-to-right through the URL hierarchy (any miss →
        ERR_NOT_FOUND)".

        Claim: GET /telemed/physicians/{bogus} returns ERR_NOT_FOUND.
        """
        res = api.get_physician(
            NON_EXISTENT_UUID, TEST_USERS["admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_nonexistent_consult(self, api):
        """PRD §2.6: "existence of all path-referenced resources,
        evaluated left-to-right through the URL hierarchy (any miss →
        ERR_NOT_FOUND)".

        Claim: GET /telemed/consults/{bogus} returns ERR_NOT_FOUND.
        """
        res = api.get_consult(
            NON_EXISTENT_UUID, TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_nonexistent_claim(self, api):
        """PRD §2.6: "existence of all path-referenced resources,
        evaluated left-to-right through the URL hierarchy (any miss →
        ERR_NOT_FOUND)".

        Claim: GET /telemed/claims/{bogus} returns ERR_NOT_FOUND.
        """
        res = api.get_claim(
            NON_EXISTENT_UUID, TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")
