"""Auth headers, RBAC, NOT_FOUND, envelope, pagination.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination),
§2.5 (path resolution / body-FK separation).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    anchor_clock,
    create_appointment_payload,
    create_patient_payload,
    create_therapist_payload,
    setup_active_licensed_therapist,
    validate_error,
    validate_paginated,
    validate_success,
)


# ===========================================================================
# §2.1 Auth — missing / malformed headers
# ===========================================================================
class TestAuthHeaders:
    """PRD §2.1: every request must carry X-User-ID and X-User-Role."""

    def test_missing_both_headers_rejected(self, api):
        """PRD §2.1: "When either header is missing or X-User-Role is
        not one of the four recognised values, the request is rejected
        with ERR_AUTH_REQUIRED (HTTP 401)."

        Claim: a request with neither header set returns
        ERR_AUTH_REQUIRED.
        """
        res = api.create_therapist(create_therapist_payload(), headers={})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "When either header is missing or X-User-Role is
        not one of the four recognised values, the request is rejected
        with ERR_AUTH_REQUIRED (HTTP 401)."

        Claim: omitting X-User-ID returns ERR_AUTH_REQUIRED.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            headers={"X-User-Role": "PracticeAdmin"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "When either header is missing or X-User-Role is
        not one of the four recognised values, the request is rejected
        with ERR_AUTH_REQUIRED (HTTP 401)."

        Claim: omitting X-User-Role returns ERR_AUTH_REQUIRED.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            headers={"X-User-ID": "practice-admin-001"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_unrecognized_role_rejected(self, api):
        """PRD §2.1: "When either header is missing or X-User-Role is
        not one of the four recognised values, the request is rejected
        with ERR_AUTH_REQUIRED (HTTP 401)."

        Claim: a role outside the four recognised values returns
        ERR_AUTH_REQUIRED.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            headers={"X-User-ID": "x-1", "X-User-Role": "Receptionist"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")


# ===========================================================================
# §2.1 / §4 RBAC — wrong role → ERR_FORBIDDEN
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: 'When the headers are well-formed but the role is not
    permitted to invoke the target endpoint, the request is rejected
    with ERR_FORBIDDEN (HTTP 403).'"""

    def test_therapist_cannot_create_therapist(self, api):
        """PRD §4 lists POST /practice/therapists as PracticeAdmin
        only.

        PRD §2.1: "When the headers are well-formed but the role is not
        permitted to invoke the target endpoint, the request is rejected
        with ERR_FORBIDDEN (HTTP 403)."

        Claim: Therapist calling POST /practice/therapists returns
        ERR_FORBIDDEN.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            TEST_USERS["therapist_fallback_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_billing_clerk_cannot_create_therapist(self, api):
        """PRD §4 lists POST /practice/therapists as PracticeAdmin
        only.

        PRD §2.1: "When the headers are well-formed but the role is not
        permitted to invoke the target endpoint, the request is rejected
        with ERR_FORBIDDEN (HTTP 403)."

        Claim: BillingClerk calling POST /practice/therapists returns
        ERR_FORBIDDEN.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            TEST_USERS["billing_clerk_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_billing_clerk_cannot_create_appointment(self, api):
        """PRD §4 lists POST /practice/appointments as PracticeAdmin |
        Therapist only.

        PRD §2.1: "When the headers are well-formed but the role is not
        permitted to invoke the target endpoint, the request is rejected
        with ERR_FORBIDDEN (HTTP 403)."

        Claim: BillingClerk calling POST /practice/appointments returns
        ERR_FORBIDDEN.
        """
        # Use a body that would otherwise pass FK validation; RBAC
        # fires at priority 2, before priority-3 path resolution.
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist()
        res = api.create_appointment(
            create_appointment_payload(
                therapist_id=therapist["id"],
                patient_id=NON_EXISTENT_UUID,
            ),
            TEST_USERS["billing_clerk_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_supervisor_cannot_create_patient(self, api):
        """PRD §4 lists POST /practice/patients as PracticeAdmin |
        Therapist only.

        PRD §2.1: "When the headers are well-formed but the role is not
        permitted to invoke the target endpoint, the request is rejected
        with ERR_FORBIDDEN (HTTP 403)."

        Claim: Supervisor calling POST /practice/patients returns
        ERR_FORBIDDEN.
        """
        res = api.create_patient(
            create_patient_payload(),
            TEST_USERS["supervisor_fallback_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.5 NOT_FOUND vs REFERENCE_NOT_FOUND
# ===========================================================================
class TestExistence:
    """PRD §2.5: 'Every nested URL path is resolved from left to
    right... rejects with ERR_NOT_FOUND ... Body-referenced foreign
    keys ... is reported as ERR_REFERENCE_NOT_FOUND.'"""

    def test_get_therapist_nonexistent_returns_not_found(self, api):
        """PRD §2.5: "rejects with ERR_NOT_FOUND (HTTP 404) the moment
        any segment fails to resolve."

        Claim: GET /practice/therapists/{nonexistent_id} returns
        ERR_NOT_FOUND.
        """
        res = api.get_therapist(
            NON_EXISTENT_UUID,
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_patient_nonexistent_returns_not_found(self, api):
        """PRD §2.5: "rejects with ERR_NOT_FOUND (HTTP 404) the moment
        any segment fails to resolve."

        Claim: GET /practice/patients/{nonexistent_id} returns
        ERR_NOT_FOUND.
        """
        res = api.get_patient(
            NON_EXISTENT_UUID,
            TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_create_supervision_assignment_with_unknown_therapist_id(
        self, api,
    ):
        """PRD §2.5: "Body-referenced foreign keys (for instance
        therapist_id, patient_id, insurance_plan_id, supervisor_id,
        trigger_assessment_id) are resolved during request-body
        validation; failure to resolve any of these is reported as
        ERR_REFERENCE_NOT_FOUND (HTTP 404)."

        Claim: POST /practice/supervision-assignments with an unknown
        therapist_id returns ERR_REFERENCE_NOT_FOUND.
        """
        anchor_clock()
        from test_helpers import (
            create_supervision_assignment_payload,
            create_supervisor,
        )
        supervisor = create_supervisor()
        payload = create_supervision_assignment_payload(
            therapist_id=NON_EXISTENT_UUID,
            supervisor_id=supervisor["id"],
        )
        res = api.create_supervision_assignment(
            payload, TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")

    def test_create_patient_with_unknown_insurance_plan_id(self, api):
        """PRD §2.5: "Body-referenced foreign keys ... is reported as
        ERR_REFERENCE_NOT_FOUND (HTTP 404)."

        Claim: POST /practice/patients with insurance_plan_id pointing
        to no plan returns ERR_REFERENCE_NOT_FOUND.
        """
        payload = create_patient_payload(
            insurance_plan_id=NON_EXISTENT_UUID,
        )
        res = api.create_patient(
            payload, TEST_USERS["practice_admin_headers"],
        )
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ===========================================================================
# §2.2 success envelope
# ===========================================================================
class TestSuccessEnvelope:
    """PRD §2.2: success responses carry meta + response_type + data."""

    def test_create_therapist_returns_full_success_envelope(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their
        JSON body: { meta: ..., response_type: object | array, data:
        ... }."

        Claim: a creation returns the envelope and the resource in data.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert isinstance(data, dict) and "id" in data, (
            "create_therapist data must contain the created resource"
        )

    def test_list_therapists_returns_paginated_envelope(self, api):
        """PRD §2.2 / §2.3: "Pagination-related fields in meta (limit,
        offset, total_count, has_more) are included for list endpoints."

        Claim: GET /practice/therapists returns an array data and a
        meta block with pagination fields.
        """
        res = api.list_therapists(
            TEST_USERS["practice_admin_headers"],
            params={"limit": 5, "offset": 0},
        )
        items, meta = validate_paginated(res)
        assert isinstance(items, list)
        for k in ("limit", "offset", "total_count", "has_more"):
            assert k in meta, f"meta missing pagination field {k!r}"


# ===========================================================================
# §2.3 pagination bounds
# ===========================================================================
class TestPaginationBounds:
    """PRD §2.3: limit ∈ [1, 100], offset >= 0."""

    @pytest.mark.parametrize("limit", [0, 101, -1])
    def test_invalid_limit_rejected(self, api, limit):
        """PRD §2.3: "limit defaults to 10, with a minimum of 1 and a
        maximum of 100; values outside this range are rejected as
        schema-validation failures."

        Claim: limit outside [1, 100] returns ERR_VALIDATION.
        """
        res = api.list_therapists(
            TEST_USERS["practice_admin_headers"],
            params={"limit": limit, "offset": 0},
        )
        validate_error(res, "ERR_VALIDATION")

    def test_negative_offset_rejected(self, api):
        """PRD §2.3: "offset defaults to 0 and must be a non-negative
        integer."

        Claim: offset < 0 returns ERR_VALIDATION.
        """
        res = api.list_therapists(
            TEST_USERS["practice_admin_headers"],
            params={"limit": 10, "offset": -1},
        )
        validate_error(res, "ERR_VALIDATION")
