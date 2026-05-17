"""Auth headers, role-based access control, NotFound, envelope.

PRD §2.1 (auth/role), §2.2 (envelope), §2.3 (pagination),
§2.6 (left-to-right path resolution / body-FK separation).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    build_user_headers,
    create_patient_payload,
    create_pcp_provider,
    create_provider_payload,
    setup_patient_with_pcp,
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
        """PRD §2.1: "Requests missing or malformed in either header
        are rejected with ERR_AUTH_REQUIRED."

        Claim: a request with neither header set returns
        ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(create_patient_payload(), headers={})
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_id_header_rejected(self, api):
        """PRD §2.1: "Requests missing or malformed in either header
        are rejected with ERR_AUTH_REQUIRED."

        Claim: omitting X-User-ID returns ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-Role": "Receptionist"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_missing_user_role_header_rejected(self, api):
        """PRD §2.1: "Requests missing or malformed in either header
        are rejected with ERR_AUTH_REQUIRED."

        Claim: omitting X-User-Role returns ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={"X-User-ID": "receptionist-001"},
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_empty_user_id_rejected(self, api):
        """PRD §2.1: "Requests missing or malformed in either header
        are rejected with ERR_AUTH_REQUIRED."

        Claim: an empty X-User-ID returns ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={
                "X-User-ID": "",
                "X-User-Role": "Receptionist",
            },
        )
        validate_error(res, "ERR_AUTH_REQUIRED")

    def test_unrecognized_role_rejected(self, api):
        """PRD §2.1: "The system recognizes eight roles, each spelled
        exactly as follows..." and "Requests missing or malformed in
        either header are rejected with ERR_AUTH_REQUIRED."

        Claim: a role that is not one of the eight known role names
        returns ERR_AUTH_REQUIRED.
        """
        res = api.create_patient(
            create_patient_payload(),
            headers={
                "X-User-ID": "x-1", "X-User-Role": "Admin",
            },
        )
        validate_error(res, "ERR_AUTH_REQUIRED")


# ===========================================================================
# §2.1 / §4 RBAC — wrong role → ERR_FORBIDDEN
# ===========================================================================
class TestRoleAuthorization:
    """PRD §2.1: "Requests carrying valid headers but invoking an
    operation outside the role's permitted set are rejected with
    ERR_FORBIDDEN.\""""

    def test_nurse_cannot_create_patient(self, api):
        """PRD §4 lists POST /patients as Receptionist | ClinicAdmin
        only.

        PRD §2.1: "Requests carrying valid headers but invoking an
        operation outside the role's permitted set are rejected with
        ERR_FORBIDDEN."

        Claim: Nurse calling POST /patients returns ERR_FORBIDDEN.
        """
        res = api.create_patient(
            create_patient_payload(), TEST_USERS["nurse_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_receptionist_cannot_create_provider(self, api):
        """PRD §4 lists POST /providers as ClinicAdmin only.

        PRD §2.1: "Requests carrying valid headers but invoking an
        operation outside the role's permitted set are rejected with
        ERR_FORBIDDEN."

        Claim: Receptionist calling POST /providers returns
        ERR_FORBIDDEN.
        """
        res = api.create_provider(
            create_provider_payload(),
            TEST_USERS["receptionist_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_receptionist_cannot_unbind_pcp(self, api):
        """PRD §3.1: "Unbinding is reserved to ClinicAdmin."

        Claim: Receptionist calling POST /patients/{id}/unbind-pcp
        returns ERR_FORBIDDEN.
        """
        patient, _ = setup_patient_with_pcp()
        res = api.unbind_pcp(
            patient["id"], TEST_USERS["receptionist_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_pharmacist_cannot_create_prescription(self, api):
        """PRD §4 lists POST /patients/{patient_id}/prescriptions as
        Provider only.

        PRD §2.1: "Requests carrying valid headers but invoking an
        operation outside the role's permitted set are rejected with
        ERR_FORBIDDEN."

        Claim: Pharmacist creating a prescription returns
        ERR_FORBIDDEN.
        """
        patient, _ = setup_patient_with_pcp()
        # We use a stub body — the role check sits at priority 2 in
        # §2.7, so it fires before any body validation.
        res = api.create_prescription(
            patient["id"],
            {"provider_id": "x", "encounter_id": "y",
             "drug_name": "X", "rxnorm_code": "12345",
             "is_controlled": False, "dose_mg": 10,
             "quantity": 1, "refills_authorized": 0,
             "dea_schedule": None},
            TEST_USERS["pharmacist_headers"],
        )
        validate_error(res, "ERR_FORBIDDEN")

    def test_billing_clerk_cannot_read_audit_logs(self, api):
        """PRD §3.9: "A ClinicAdmin is the only role permitted to
        read audit logs."

        Claim: BillingClerk calling GET /audit-logs returns
        ERR_FORBIDDEN.
        """
        res = api.list_audit_logs(TEST_USERS["billing_clerk_headers"])
        validate_error(res, "ERR_FORBIDDEN")


# ===========================================================================
# §2.6 / §2.7 NotFound and body-FK separation
# ===========================================================================
class TestNotFoundAndReferences:
    """PRD §2.6: left-to-right path resolution, body FKs after."""

    def test_get_nonexistent_patient_returns_not_found(self, api):
        """PRD §2.6: "the system resolves the path segments strictly
        left-to-right and returns ERR_NOT_FOUND against the first
        segment whose target does not exist."

        Claim: GET /patients/{nonexistent} returns ERR_NOT_FOUND.
        """
        res = api.get_patient(
            NON_EXISTENT_UUID, TEST_USERS["receptionist_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_get_nonexistent_provider_returns_not_found(self, api):
        """PRD §2.6: "the system resolves the path segments strictly
        left-to-right and returns ERR_NOT_FOUND against the first
        segment whose target does not exist."

        Claim: GET /providers/{nonexistent} returns ERR_NOT_FOUND.
        """
        res = api.get_provider(
            NON_EXISTENT_UUID, TEST_USERS["receptionist_headers"],
        )
        validate_error(res, "ERR_NOT_FOUND")

    def test_bind_pcp_body_fk_provider_missing(self, api):
        """PRD §2.6: "Body foreign-key references — patient_id,
        provider_id, encounter_id, the cpt_code referenced by a
        billing line — are resolved separately, after the path is
        fully valid; a missing body reference yields
        ERR_REFERENCE_NOT_FOUND."

        Claim: bind-pcp with a non-existent provider_id returns
        ERR_REFERENCE_NOT_FOUND (path is valid).
        """
        # Build a Patient first so the path is valid.
        from test_helpers import create_patient
        patient = create_patient()
        res = api.bind_pcp(
            patient["id"],
            {"provider_id": NON_EXISTENT_UUID},
            TEST_USERS["receptionist_headers"],
        )
        validate_error(res, "ERR_REFERENCE_NOT_FOUND")


# ===========================================================================
# §2.2 envelope structure validated by validate_success / paginated
# ===========================================================================
class TestEnvelope:
    """PRD §2.2 success and error envelope."""

    def test_success_envelope_on_create_patient(self, api,
                                                 receptionist_headers):
        """PRD §2.2: success responses carry meta with
        api_request_id and api_request_timestamp, response_type
        ('object' or 'array'), and data.

        Claim: a successful POST /patients returns 201 with a Patient
        object in data.
        """
        res = api.create_patient(
            create_patient_payload(), receptionist_headers,
        )
        body = validate_success(res, expected_status=201)
        assert "id" in body, "data must contain Patient id"

    def test_paginated_envelope_on_list_patients(self, api,
                                                  receptionist_headers):
        """PRD §2.2 / §2.3: list endpoints include limit, offset,
        total_count, has_more in meta.

        Claim: GET /patients returns a paginated envelope with all
        four meta keys.
        """
        for _ in range(3):
            api.create_patient(
                create_patient_payload(), receptionist_headers,
            )
        res = api.list_patients(receptionist_headers)
        data, meta = validate_paginated(res)
        assert "total_count" in meta
        assert "limit" in meta
        assert "offset" in meta
        assert "has_more" in meta
        assert meta["total_count"] >= 3


# ===========================================================================
# §2.3 Pagination behavior
# ===========================================================================
class TestPagination:
    """PRD §2.3."""

    def test_list_patients_limit_one_returns_one(self, api,
                                                  receptionist_headers):
        """PRD §2.3: "limit controls the maximum number of items
        returned: it defaults to 10, has a minimum of 1, and a
        maximum of 100."

        Claim: limit=1 returns exactly one item.
        """
        for _ in range(2):
            api.create_patient(
                create_patient_payload(), receptionist_headers,
            )
        res = api.list_patients(
            receptionist_headers, params={"limit": 1},
        )
        data, _ = validate_paginated(res)
        assert len(data) == 1

    def test_list_patients_high_offset_returns_empty(
        self, api, receptionist_headers,
    ):
        """PRD §2.3: "offset is the number of items skipped before
        the page begins; it defaults to 0."

        Claim: offset beyond total_count returns empty list with
        has_more=false.
        """
        api.create_patient(
            create_patient_payload(), receptionist_headers,
        )
        res = api.list_patients(
            receptionist_headers, params={"offset": 99999},
        )
        data, meta = validate_paginated(res)
        assert data == []
        assert meta["has_more"] is False


# ===========================================================================
# §2.12 Portal access ownership
# ===========================================================================
class TestPortalAccessOwnership:
    """PRD §2.12: ownership-gated patient portal reads."""

    def test_portal_user_cannot_read_other_patients_record(self, api):
        """PRD §2.12: "only the patient themselves, acting as
        PatientPortalUser with X-User-ID equal to the Patient.id and
        with portal_enabled true on that patient, may exercise portal
        read operations on patient-scoped resources; any other
        combination is rejected with ERR_PORTAL_DISABLED."

        Claim: a PatientPortalUser whose X-User-ID belongs to one
        patient cannot read another patient's record.
        """
        from test_helpers import create_patient, make_patient_portal_headers
        patient_a = create_patient(portal_enabled=True)
        patient_b = create_patient(portal_enabled=True)
        # Act as patient_a; try to read patient_b.
        headers = make_patient_portal_headers(patient_a["id"])
        res = api.get_patient(patient_b["id"], headers)
        validate_error(res, "ERR_PORTAL_DISABLED")

    def test_portal_user_with_portal_disabled_cannot_read_own_record(
        self, api,
    ):
        """PRD §2.12: "only the patient themselves, acting as
        PatientPortalUser with X-User-ID equal to the Patient.id and
        with portal_enabled true on that patient, may exercise portal
        read operations on patient-scoped resources; any other
        combination is rejected with ERR_PORTAL_DISABLED."

        Claim: a PatientPortalUser whose Patient.portal_enabled is
        false is rejected with ERR_PORTAL_DISABLED.
        """
        from test_helpers import create_patient, make_patient_portal_headers
        patient = create_patient(portal_enabled=False)
        headers = make_patient_portal_headers(patient["id"])
        res = api.get_patient(patient["id"], headers)
        validate_error(res, "ERR_PORTAL_DISABLED")
