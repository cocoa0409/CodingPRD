"""Therapist and Patient registration.

PRD §3.1 covers the input shape, the credential→can_evaluate
derivation, the NPI uniqueness rule, and the conditional payer fields.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    assert_patient,
    assert_therapist,
    create_patient_payload,
    create_therapist_payload,
    random_npi,
    validate_error,
    validate_success,
)


# ===========================================================================
# Therapist registration — PRD §3.1.
# ===========================================================================
class TestTherapistRegistration:

    def test_create_pt_yields_can_evaluate_true(self, api):
        """PRD §3.1: "can_evaluate automatically: it is true when the
        credential is PT or DPT, and false when the credential is
        PTA."

        Claim: credential=PT → can_evaluate=true on response.
        """
        res = api.create_therapist(
            create_therapist_payload(credential="PT"),
            TEST_USERS["clinic_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_therapist(data)
        assert data["credential"] == "PT"
        assert data["can_evaluate"] is True

    def test_create_dpt_yields_can_evaluate_true(self, api):
        """PRD §3.1: "it is true when the credential is PT or DPT."

        Claim: credential=DPT → can_evaluate=true.
        """
        res = api.create_therapist(
            create_therapist_payload(credential="DPT"),
            TEST_USERS["clinic_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_therapist(data)
        assert data["can_evaluate"] is True

    def test_create_pta_yields_can_evaluate_false(self, api):
        """PRD §3.1: "false when the credential is PTA. A physical
        therapist assistant may deliver visits, but they cannot
        finalize or amend evaluations and they cannot sign a discharge."

        Claim: credential=PTA → can_evaluate=false.
        """
        res = api.create_therapist(
            create_therapist_payload(credential="PTA"),
            TEST_USERS["clinic_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_therapist(data)
        assert data["credential"] == "PTA"
        assert data["can_evaluate"] is False

    def test_create_therapist_starts_active(self, api):
        """PRD §3.1: "New therapists begin life in status ACTIVE."

        Claim: newly created Therapist.status == ACTIVE.
        """
        res = api.create_therapist(
            create_therapist_payload(),
            TEST_USERS["clinic_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["status"] == "ACTIVE"

    def test_duplicate_npi_rejected(self, api):
        """PRD §3.1: "Attempting to register a second therapist with
        an npi that already exists yields ERR_DUPLICATE_NPI."

        Claim: second create with same npi → ERR_DUPLICATE_NPI.
        """
        npi = random_npi()
        res1 = api.create_therapist(
            create_therapist_payload(npi=npi, credential="PT"),
            TEST_USERS["clinic_admin_headers"],
        )
        validate_success(res1, expected_status=201)
        res2 = api.create_therapist(
            create_therapist_payload(npi=npi, credential="DPT",
                                     full_name="Dr. Twin"),
            TEST_USERS["clinic_admin_headers"],
        )
        validate_error(res2, "ERR_DUPLICATE_NPI")


# ===========================================================================
# Patient registration — PRD §3.1.
# ===========================================================================
class TestPatientRegistration:

    def test_create_commercial_patient(self, api):
        """PRD §3.1: "Registering a patient supplies full_name,
        date_of_birth, and insurance_type, the latter being one of
        MEDICARE_PART_B, VA, COMMERCIAL, or SELF_PAY."

        Claim: COMMERCIAL patient is created in ACTIVE with
        ytd_capped_amount_cents=0.
        """
        res = api.create_patient(
            create_patient_payload(insurance_type="COMMERCIAL"),
            TEST_USERS["clinic_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert_patient(data)
        assert data["insurance_type"] == "COMMERCIAL"
        assert data["status"] == "ACTIVE"
        # PRD §3.1: "The cap counter ytd_capped_amount_cents is
        # initialized to 0..."
        assert data["ytd_capped_amount_cents"] == 0

    def test_create_self_pay_patient_starts_with_zero_ytd(self, api):
        """PRD §3.1: "The cap counter ytd_capped_amount_cents is
        initialized to 0 and only ever grows as Medicare-Part-B-covered
        visits sign."

        Claim: SELF_PAY patient is created with
        ytd_capped_amount_cents=0.
        """
        res = api.create_patient(
            create_patient_payload(insurance_type="SELF_PAY"),
            TEST_USERS["clinic_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["ytd_capped_amount_cents"] == 0

    def test_create_medicare_patient_with_mbi(self, api):
        """PRD §3.1: "when insurance_type is MEDICARE_PART_B, the
        patient's medicare_beneficiary_id is required and is the MBI
        used on every Medicare claim."

        Claim: MEDICARE_PART_B + mbi → 201 created.
        """
        res = api.create_patient(
            create_patient_payload(insurance_type="MEDICARE_PART_B"),
            TEST_USERS["clinic_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["insurance_type"] == "MEDICARE_PART_B"
        assert data.get("medicare_beneficiary_id"), (
            "Patient.medicare_beneficiary_id must be present on a "
            "MEDICARE_PART_B patient"
        )

    def test_create_va_patient_with_referral_id(self, api):
        """PRD §3.1: "when insurance_type is VA, the patient's
        va_referral_id is required and is the VA Community Care
        Network referral identifier."

        Claim: VA + va_referral_id → 201 created.
        """
        res = api.create_patient(
            create_patient_payload(insurance_type="VA"),
            TEST_USERS["clinic_admin_headers"],
        )
        data = validate_success(res, expected_status=201)
        assert data["insurance_type"] == "VA"
        assert data.get("va_referral_id"), (
            "Patient.va_referral_id must be present on a VA patient"
        )
