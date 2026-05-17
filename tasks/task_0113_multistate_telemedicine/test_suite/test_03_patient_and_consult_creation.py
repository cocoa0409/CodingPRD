"""Patient registration, patient update, consult creation guardrails.

PRD §3.2 (patient registration / snapshotting), §3.3 (consult creation
+ ERR_INSURANCE_NOT_ENROLLED + ERR_PATIENT_HAS_ACTIVE_CONSULT).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_consult,
    assert_patient,
    close_consult,
    complete_consult,
    create_consult,
    create_consult_payload,
    create_insured_patient,
    create_patient,
    create_patient_payload,
    decline_consult,
    mark_paid_invoice,
    random_member_id,
    random_payer_id,
    re_get_consult,
    setup_completed_consult,
    setup_in_progress_consult,
    setup_patient_with_routed_consult_for_overlap,
    setup_physician_with_license,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.2 Patient registration
# ===========================================================================
class TestPatientRegistration:

    def test_create_patient_with_minimum_fields(self, api):
        """PRD §3.2: "A PlatformAdmin registers a patient by submitting
        full_name, date_of_birth, the patient's two-letter
        home_state_code, and optionally a present_state_code".

        Claim: a minimal payload (full_name, date_of_birth,
        home_state_code) creates the patient.
        """
        res = api.create_patient(
            create_patient_payload(home_state_code="CA"),
            TEST_USERS["admin_headers"],
        )
        data = validate_success(res, 201)
        assert_patient(data)
        assert data["home_state_code"] == "CA"

    def test_create_patient_with_insurance(self, api):
        """PRD §3.2: "Patients enrolled with an insurance carrier
        additionally supply insurance_payer_id, insurance_member_id,
        the remaining annual deductible balance in cents
        (insurance_deductible_remaining_cents), a flat copay amount in
        cents (insurance_copay_cents), and a coinsurance percentage
        stored as basis points (insurance_coinsurance_bps".

        Claim: a payload with all five insurance fields creates the
        patient with those fields persisted.
        """
        payload = create_patient_payload(
            home_state_code="CA",
            insurance_payer_id=random_payer_id(),
            insurance_member_id=random_member_id(),
            insurance_deductible_remaining_cents=2000,
            insurance_copay_cents=1500,
            insurance_coinsurance_bps=2000,
        )
        res = api.create_patient(payload, TEST_USERS["admin_headers"])
        data = validate_success(res, 201)
        assert data["insurance_deductible_remaining_cents"] == 2000
        assert data["insurance_copay_cents"] == 1500
        assert data["insurance_coinsurance_bps"] == 2000


# ===========================================================================
# §3.2 present_state_code snapshotting
# ===========================================================================
class TestPresentStateSnapshot:
    """PRD §3.2: "a patient's present_state_code is read at consult
    creation time and snapshotted onto the consult; later edits to the
    patient record do not retroactively change a consult's
    present_state_code.\""""

    def test_consult_snapshots_patient_present_state(self, api):
        """PRD §3.2: "a patient's present_state_code is read at consult
        creation time and snapshotted onto the consult".

        Claim: after creating a consult whose present_state_code is
        derived from the patient, mutating the Patient's
        present_state_code does NOT update the existing consult's
        present_state_code.
        """
        physician, _ = setup_physician_with_license(state_code="CA")
        patient = create_patient(home_state_code="CA")
        consult = create_consult(
            patient=patient, billing_mode="SELF_PAY",
            visit_tier="STANDARD", present_state_code="CA",
        )
        # Mutate patient's present_state_code.
        res = api.patch_patient(
            patient["id"], {"present_state_code": "NY"},
            TEST_USERS["admin_headers"],
        )
        validate_success(res, 200)
        # Re-read the consult.
        refreshed = re_get_consult(consult["id"])
        assert refreshed["present_state_code"] == "CA", (
            f"PRD §3.2 snapshot: consult.present_state_code must be "
            f"unchanged by Patient mutation; got "
            f"{refreshed['present_state_code']!r}"
        )


# ===========================================================================
# §3.3 Consult creation guardrails
# ===========================================================================
class TestConsultCreationGuardrails:

    def test_insurance_consult_without_enrollment_rejected(self, api):
        """PRD §3.3: "if billing_mode is INSURANCE, the patient's
        record must already contain both insurance_payer_id and
        insurance_member_id; if either is missing, the consult creation
        is rejected with ERR_INSURANCE_NOT_ENROLLED."

        Claim: creating a Consult with billing_mode=INSURANCE for a
        patient that lacks insurance_payer_id returns
        ERR_INSURANCE_NOT_ENROLLED.
        """
        patient = create_patient(home_state_code="CA")
        res = api.create_consult(
            create_consult_payload(
                patient_id=patient["id"],
                billing_mode="INSURANCE",
                visit_tier="STANDARD",
                present_state_code="CA",
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_INSURANCE_NOT_ENROLLED")

    def test_patient_with_active_consult_rejected(self, api):
        """PRD §3.3: "the patient must not currently own another consult
        in a non-terminal status — meaning any of REQUESTED, ROUTED,
        IN_PROGRESS, or COMPLETED — and a violation surfaces as
        ERR_PATIENT_HAS_ACTIVE_CONSULT."

        Claim: creating a second consult for a patient that already
        owns a ROUTED consult returns ERR_PATIENT_HAS_ACTIVE_CONSULT.

        difficulty: resource_temporal_overlap/patient_active_consult_status_window_overlap
        """
        physician, _, patient, consult = (
            setup_patient_with_routed_consult_for_overlap()
        )
        # consult.status == ROUTED → patient occupied.
        res = api.create_consult(
            create_consult_payload(
                patient_id=patient["id"],
                billing_mode="SELF_PAY",
                visit_tier="BRIEF",
                present_state_code="CA",
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        validate_error(res, "ERR_PATIENT_HAS_ACTIVE_CONSULT")

    def test_declined_consult_releases_patient(self, api):
        """PRD §3.3: "The two terminal states CLOSED and DECLINED do not
        block a new consult."

        Claim: after a consult reaches DECLINED, a new consult for the
        same patient is accepted.

        difficulty: resource_temporal_overlap/patient_active_consult_status_window_overlap
        """
        physician, _ = setup_physician_with_license()
        patient = create_patient(home_state_code="CA")
        first = create_consult(
            patient=patient, billing_mode="SELF_PAY",
            visit_tier="BRIEF", present_state_code="CA",
        )
        # Decline first consult → DECLINED.
        decline_consult(consult=first)
        # New consult for same patient should succeed.
        res = api.create_consult(
            create_consult_payload(
                patient_id=patient["id"],
                billing_mode="SELF_PAY",
                visit_tier="BRIEF",
                present_state_code="CA",
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        data = validate_success(res, 201)
        assert_consult(data)
        assert data["status"] == "REQUESTED"


# ===========================================================================
# §3.3 Consult default-state assertions
# ===========================================================================
class TestConsultCreationDefaults:

    def test_consult_created_in_requested_with_null_physician(self, api):
        """PRD §3.3: "The consult is created in REQUESTED status with
        physician_id set to null and routing_basis set to null; these
        are filled in only when compliance routing succeeds."

        Claim: a freshly-created consult has status=REQUESTED, no
        physician_id, no routing_basis.
        """
        physician, _ = setup_physician_with_license()
        patient = create_patient(home_state_code="CA")
        res = api.create_consult(
            create_consult_payload(
                patient_id=patient["id"],
                billing_mode="SELF_PAY",
                visit_tier="STANDARD",
                present_state_code="CA",
            ),
            TEST_USERS["compliance_officer_headers"],
        )
        data = validate_success(res, 201)
        assert data["status"] == "REQUESTED"
        # PRD §3.3: "physician_id set to null and routing_basis set to
        # null". A faithful implementation may return the key with null
        # or omit it; we accept either.
        assert data.get("physician_id") in (None, "")
        assert data.get("routing_basis") in (None, "")
