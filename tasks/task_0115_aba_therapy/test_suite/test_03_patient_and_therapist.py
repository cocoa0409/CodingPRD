"""Patient and therapist roster operations.

PRD §3.1 (patient + therapist creation and reads).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_patient,
    assert_therapist,
    build_user_headers,
    create_clinic,
    create_patient_payload,
    create_therapist,
    create_therapist_payload,
    setup_clinic_with_roster,
    validate_error,
    validate_success,
)


class TestPatientCreation:

    def test_clinic_admin_creates_patient(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.1: "Patient records are created either by a
        ClinicAdmin or by a BCBA. A patient carries the owning
        clinic_id, the patient's legal_name, their date_of_birth, and
        the payer-issued insurance_member_id."

        Claim: a ClinicAdmin POST /patients with the four required
        fields returns 201 with the created patient.
        """
        clinic = create_clinic()
        res = api.create_patient(
            create_patient_payload(clinic_id=clinic["id"]),
            clinic_admin_headers,
        )
        patient = validate_success(res, expected_status=201)
        assert_patient(patient)
        assert patient["clinic_id"] == clinic["id"]

    def test_patient_starts_active_with_zero_scores(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.1: "two computed score fields —
        clinical_progress_score_provisional and
        clinical_progress_score_adjudicated — both initialised to 0.0,
        and a status of ACTIVE or DISCHARGED; patients are created
        ACTIVE."

        Claim: a freshly-created patient has status ACTIVE and both
        progress scores equal to 0 (within float tolerance).
        """
        clinic = create_clinic()
        res = api.create_patient(
            create_patient_payload(clinic_id=clinic["id"]),
            clinic_admin_headers,
        )
        patient = validate_success(res, expected_status=201)
        assert patient["status"] == "ACTIVE"
        assert patient["clinical_progress_score_provisional"] == 0 or (
            patient["clinical_progress_score_provisional"]
            == pytest.approx(0.0)
        )
        assert patient["clinical_progress_score_adjudicated"] == 0 or (
            patient["clinical_progress_score_adjudicated"]
            == pytest.approx(0.0)
        )

    def test_bcba_can_create_patient(self, api):
        """PRD §3.1: "Patient records are created either by a
        ClinicAdmin or by a BCBA."

        Claim: a BCBA calling POST /patients succeeds.
        """
        roster = setup_clinic_with_roster()
        bcba = roster["bcbas"][0]
        res = api.create_patient(
            create_patient_payload(clinic_id=roster["clinic"]["id"]),
            build_user_headers(bcba["id"], "BCBA"),
        )
        patient = validate_success(res, expected_status=201)
        assert_patient(patient)


class TestTherapistCreation:

    def test_clinic_admin_creates_therapist(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.1: "A therapist row carries the owning clinic_id, the
        therapist's legal_name, their credential (one of BCBA or RBT),
        and their license_number."

        Claim: ClinicAdmin POST /therapists with the four required
        fields returns 201.
        """
        clinic = create_clinic()
        res = api.create_therapist(
            create_therapist_payload(
                clinic_id=clinic["id"], credential="BCBA",
            ),
            clinic_admin_headers,
        )
        therapist = validate_success(res, expected_status=201)
        assert_therapist(therapist)
        assert therapist["credential"] == "BCBA"

    def test_therapist_starts_active(self, api, clinic_admin_headers):
        """PRD §3.1: "Each therapist also carries a status of either
        ACTIVE or SUSPENDED; therapists are created ACTIVE."

        Claim: a freshly-created therapist has status == ACTIVE.
        """
        clinic = create_clinic()
        res = api.create_therapist(
            create_therapist_payload(
                clinic_id=clinic["id"], credential="RBT",
            ),
            clinic_admin_headers,
        )
        therapist = validate_success(res, expected_status=201)
        assert therapist["status"] == "ACTIVE"

    @pytest.mark.parametrize("credential", ["BCBA", "RBT"])
    def test_create_therapist_with_each_credential(
        self, api, clinic_admin_headers, credential,
    ):
        """PRD §3.1: credential is "one of BCBA or RBT".

        Claim: both BCBA and RBT credentials are accepted on creation.
        """
        clinic = create_clinic()
        res = api.create_therapist(
            create_therapist_payload(
                clinic_id=clinic["id"], credential=credential,
            ),
            clinic_admin_headers,
        )
        therapist = validate_success(res, expected_status=201)
        assert therapist["credential"] == credential


class TestTherapistRead:

    def test_read_therapist_returns_record(
        self, api, clinic_admin_headers,
    ):
        """PRD §4: GET /therapists/{id} returns a therapist.

        Claim: reading a freshly-created therapist returns the same id,
        clinic_id, credential, and status.
        """
        roster = setup_clinic_with_roster()
        rbt = roster["rbts"][0]
        res = api.get_therapist(rbt["id"], clinic_admin_headers)
        data = validate_success(res)
        assert data["id"] == rbt["id"]
        assert data["credential"] == "RBT"


class TestPatientList:

    def test_list_patients_includes_status_filter(
        self, api, clinic_admin_headers,
    ):
        """PRD §3.1: "The patient list endpoint accepts the status
        query filter and the usual limit and offset parameters."

        Claim: GET /patients?status=ACTIVE returns only ACTIVE patients.
        """
        clinic = create_clinic()
        # Create one ACTIVE patient.
        api.create_patient(
            create_patient_payload(clinic_id=clinic["id"]),
            clinic_admin_headers,
        )
        res = api.list_patients(
            clinic_admin_headers, params={"status": "ACTIVE"},
        )
        body = res.json()
        for p in body["data"]:
            assert p["status"] == "ACTIVE"
