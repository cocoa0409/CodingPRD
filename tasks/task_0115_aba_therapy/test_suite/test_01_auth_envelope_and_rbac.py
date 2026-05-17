"""Auth, RBAC, response envelope, pagination, and existence checks.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination), §2.7
(NotFound / left-to-right resolution).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_clinic,
    create_clinic_payload,
    create_patient,
    create_patient_payload,
    create_therapist_payload,
    setup_basic_environment,
    setup_clinic_with_roster,
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
        """PRD §2.1: "Every request must carry two HTTP headers:
        X-User-ID and X-User-Role. If either is missing or empty, the
        response is ERR_AUTH_REQUIRED with HTTP 401."

        Claim: a POST with neither header set returns ERR_AUTH_REQUIRED.
        """
        res = api.create_clinic(create_clinic_payload(), headers={})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers:
        X-User-ID and X-User-Role. If either is missing or empty, the
        response is ERR_AUTH_REQUIRED with HTTP 401."

        Claim: omitting X-User-ID returns ERR_AUTH_REQUIRED.
        """
        res = api.create_clinic(
            create_clinic_payload(),
            headers={"X-User-Role": "ClinicAdmin"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Every request must carry two HTTP headers:
        X-User-ID and X-User-Role. If either is missing or empty, the
        response is ERR_AUTH_REQUIRED with HTTP 401."

        Claim: omitting X-User-Role returns ERR_AUTH_REQUIRED.
        """
        res = api.create_clinic(
            create_clinic_payload(),
            headers={"X-User-ID": "clinic-admin-001"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_unknown_role_value_rejected(self, api):
        """PRD §2.1: "If the role string is not one of the four
        recognised values, the same code applies."

        Claim: a role outside {BCBA, RBT, ClinicAdmin, PayerAdmin}
        returns ERR_AUTH_REQUIRED.
        """
        res = api.create_clinic(
            create_clinic_payload(),
            headers=build_user_headers("op-1", "SuperUser"),
        )
        validate_error(res, "ERR_AUTH_REQUIRED")


# ===========================================================================
# §2.1 RBAC — wrong role for endpoint
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "If the role is recognised but is not in the RBAC
    matrix for the requested endpoint, the response is ERR_FORBIDDEN
    with HTTP 403."""

    def test_bcba_cannot_create_clinic(self, api, bcba_fallback_headers):
        """PRD §4: POST /clinics is exclusive to ClinicAdmin.

        PRD §2.1: "If the role is recognised but is not in the RBAC
        matrix for the requested endpoint, the response is ERR_FORBIDDEN
        with HTTP 403."

        Claim: a BCBA calling POST /clinics returns ERR_FORBIDDEN.
        """
        res = api.create_clinic(
            create_clinic_payload(), bcba_fallback_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_payer_admin_cannot_create_clinic(self, api,
                                              payer_admin_headers):
        """PRD §4: POST /clinics is exclusive to ClinicAdmin.

        PRD §2.1: "If the role is recognised but is not in the RBAC
        matrix for the requested endpoint, the response is ERR_FORBIDDEN
        with HTTP 403."

        Claim: a PayerAdmin calling POST /clinics returns ERR_FORBIDDEN.
        """
        res = api.create_clinic(
            create_clinic_payload(), payer_admin_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_clinic_admin_cannot_approve_authorization(
        self, api, clinic_admin_headers,
    ):
        """PRD §4: POST /authorizations/{id}/approve is exclusive to
        PayerAdmin.

        PRD §2.1: "If the role is recognised but is not in the RBAC
        matrix for the requested endpoint, the response is ERR_FORBIDDEN
        with HTTP 403."

        Claim: a ClinicAdmin calling /approve returns ERR_FORBIDDEN.
        """
        # We don't need a real authorization id — RBAC is checked before
        # existence (PRD §2.8).
        res = api.approve_authorization(
            NON_EXISTENT_UUID, clinic_admin_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_rbt_cannot_dispute_session(self, api, rbt_fallback_headers):
        """PRD §4: POST /sessions/{id}/dispute is exclusive to BCBA.

        PRD §2.1: "If the role is recognised but is not in the RBAC
        matrix for the requested endpoint, the response is ERR_FORBIDDEN
        with HTTP 403."

        Claim: an RBT calling /dispute returns ERR_FORBIDDEN.
        """
        res = api.dispute_session(
            NON_EXISTENT_UUID,
            {"dispute_reason": "x"},
            rbt_fallback_headers,
        )
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.2 Response envelope
# ===========================================================================
class TestResponseEnvelope:
    """PRD §2.2: every response carries a meta + response_type + data
    envelope."""

    def test_success_envelope_shape(self, api, clinic_admin_headers):
        """PRD §2.2: "All successful API responses (those with 2xx
        status codes) follow this standard envelope format in their JSON
        body".

        Claim: a successful POST /clinics returns a 2xx whose body has
        meta.api_request_id (prefixed with "req_"), meta.api_request_timestamp,
        response_type == "object", and data containing the resource.
        """
        res = api.create_clinic(
            create_clinic_payload(), clinic_admin_headers,
        )
        body = res.json()
        assert "meta" in body
        assert "api_request_id" in body["meta"]
        # PRD §2.2: "starts with req_".
        assert body["meta"]["api_request_id"].startswith("req_")
        assert "api_request_timestamp" in body["meta"]
        assert body.get("response_type") == "object"
        assert isinstance(body.get("data"), dict)

    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow
        this standard envelope format … data: { error_id …, message …}".

        Claim: an unauthenticated POST returns a 4xx whose body has
        response_type == "error" and data containing error_id and message.
        """
        res = api.create_clinic(create_clinic_payload(), headers={})
        body = res.json()
        assert body.get("response_type") == "error"
        assert "data" in body
        assert "error_id" in body["data"]
        assert "message" in body["data"]


# ===========================================================================
# §2.3 Pagination
# ===========================================================================
class TestPagination:
    """PRD §2.3: list endpoints accept limit and offset, both with
    bounds."""

    @pytest.mark.parametrize("limit", [0, -1, 101, 200])
    def test_invalid_limit_rejected(
        self, api, clinic_admin_headers, limit,
    ):
        """PRD §2.3: "The default limit is 10; the minimum accepted
        value is 1 and the maximum accepted value is 100. … When either
        is violated, the response is ERR_PAGINATION_PARAMS with HTTP
        422."

        Claim: limit outside [1, 100] returns ERR_PAGINATION_PARAMS.
        """
        res = api.list_patients(
            clinic_admin_headers, params={"limit": limit},
        )
        validate_error(res, "ERR_PAGINATION_PARAMS")

    @pytest.mark.parametrize("offset", [-1, -10])
    def test_negative_offset_rejected(
        self, api, clinic_admin_headers, offset,
    ):
        """PRD §2.3: "The default offset is 0; values less than 0 are
        rejected. When either is violated, the response is
        ERR_PAGINATION_PARAMS with HTTP 422."

        Claim: negative offset returns ERR_PAGINATION_PARAMS.
        """
        res = api.list_patients(
            clinic_admin_headers, params={"offset": offset},
        )
        validate_error(res, "ERR_PAGINATION_PARAMS")

    def test_default_pagination_metadata(self, api, clinic_admin_headers):
        """PRD §2.3: "The meta object for list responses exposes limit,
        offset, total_count (the unfiltered count after status,
        session_type, or other filters are applied but before paging),
        and has_more (true when more rows remain after the current
        page)."

        Claim: list response meta includes limit, offset, total_count,
        has_more.
        """
        clinic = create_clinic()
        create_patient(clinic_id=clinic["id"])
        res = api.list_patients(clinic_admin_headers)
        data, meta = validate_paginated(res)
        assert "limit" in meta
        assert "offset" in meta
        assert "total_count" in meta
        assert "has_more" in meta


# ===========================================================================
# §2.7 NotFound — path resolution left-to-right
# ===========================================================================
class TestNotFound:
    """PRD §2.7: path segments resolve left-to-right; first missing
    segment yields ERR_NOT_FOUND."""

    def test_unknown_patient_id_in_path_yields_not_found(
        self, api, clinic_admin_headers,
    ):
        """PRD §2.7: "The first missing segment along the path causes
        the request to fail with ERR_NOT_FOUND and HTTP 404."

        Claim: GET /patients/{patient_id} with a UUID that doesn't exist
        returns ERR_NOT_FOUND.
        """
        res = api.get_patient(NON_EXISTENT_UUID, clinic_admin_headers)
        validate_error(res, "ERR_NOT_FOUND")

    def test_unknown_authorization_id_in_path_yields_not_found(
        self, api, payer_admin_headers,
    ):
        """PRD §2.7: "The first missing segment along the path causes
        the request to fail with ERR_NOT_FOUND and HTTP 404."

        Claim: POST /authorizations/{id}/approve on a missing id
        returns ERR_NOT_FOUND.
        """
        res = api.approve_authorization(
            NON_EXISTENT_UUID, payer_admin_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_unknown_body_fk_yields_not_found(
        self, api, clinic_admin_headers,
    ):
        """PRD §2.7: "After the path is fully resolved, foreign-key
        fields in the request body (for example treatment_plan_id,
        authorization_id, the elements of session_ids,
        evaluator_therapist_id) are then resolved; any unresolved body
        FK yields the same ERR_NOT_FOUND outcome with HTTP 404."

        Claim: POST /therapists with a clinic_id that doesn't resolve
        returns ERR_NOT_FOUND.
        """
        res = api.create_therapist(
            create_therapist_payload(clinic_id=NON_EXISTENT_UUID),
            clinic_admin_headers,
        )
        validate_error(res, "ERR_NOT_FOUND")


# ===========================================================================
# §2.4 Common resource fields
# ===========================================================================
class TestCommonResourceFields:
    """PRD §2.4: id (UUID, no prefix), created_at, updated_at, version."""

    def test_clinic_carries_common_fields(self, api, clinic_admin_headers):
        """PRD §2.4: "Most entities — Clinic, Patient,
        DiagnosticEvaluation, TreatmentPlan, Authorization, Therapist,
        TherapySession, and InsuranceClaim — additionally carry
        updated_at … and version".

        Claim: a freshly-created clinic includes id, created_at,
        updated_at, version == 1.
        """
        res = api.create_clinic(
            create_clinic_payload(), clinic_admin_headers,
        )
        clinic = validate_success(res, expected_status=201)
        assert "id" in clinic
        assert "created_at" in clinic
        assert "updated_at" in clinic
        assert clinic.get("version") == 1
