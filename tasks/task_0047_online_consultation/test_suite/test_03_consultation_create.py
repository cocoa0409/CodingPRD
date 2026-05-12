"""Consultation creation: doctor selection, emergency block,
preferred-doctor eligibility, capacity, REAL_TIME vs APPOINTMENT.
Covers PRD §3.3, §3.4."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    create_consultation_payload,
    create_doctor,
    create_patient,
    create_pharmacist,
    make_patient_headers,
    open_and_assess_triage,
    register_department_mapping,
    setup_basic_org,
    setup_consultation_pending,
    build_responses_for_band,
    validate_error,
    validate_success,
    create_consultation,
    DEFAULT_DEPARTMENT_CODE,
    DEFAULT_REGION_CODE,
    IN_SCOPE_DISEASE,
    OUT_OF_SCOPE_DISEASE,
)


# =========================================================================
# Emergency triage blocks consultation creation.
# =========================================================================
class TestEmergencyBlocks:

    def test_consultation_against_emergency_routed_rejected(self, api):
        """PRD §3.2: 'subsequently rejects any attempt to create a
        Consultation against this triage session with
        ERR_TRIAGE_EMERGENCY_ROUTED.'

        Claim: POST /consultations against EMERGENCY_ROUTED triage ->
        422 ERR_TRIAGE_EMERGENCY_ROUTED.
        """
        setup_basic_org()
        patient = create_patient()
        triage = open_and_assess_triage(
            patient=patient,
            responses=build_responses_for_band("EMERGENCY"),
        )
        res = api.create_consultation(
            create_consultation_payload(
                triage_session_id=triage["id"],
                mode="REAL_TIME", media_type="TEXT_IMAGE",
            ),
            make_patient_headers(patient["id"]),
        )
        validate_error(res, ApiErrorId.ERR_TRIAGE_EMERGENCY_ROUTED.value)


# =========================================================================
# REAL_TIME mode: PENDING -> QUEUED with queue_position.
# =========================================================================
class TestRealTimeMode:

    def test_real_time_consultation_queued(self, api):
        """PRD §3.4: 'For REAL_TIME, the system advances session_status
        from PENDING to QUEUED and assigns a queue_position equal to one
        plus the count of consultation rows for the same doctor_id whose
        session_status is in QUEUED, ACCEPTED, or IN_PROGRESS.'

        Claim: first REAL_TIME consultation -> session_status QUEUED,
        queue_position == 1.
        """
        state = setup_consultation_pending(mode="REAL_TIME")
        c = state["consultation"]
        assert c["session_status"] == "QUEUED"
        assert c["queue_position"] == 1


# =========================================================================
# APPOINTMENT mode: PENDING -> ACCEPTED.
# =========================================================================
class TestAppointmentMode:

    def test_appointment_consultation_accepted_without_queue(self, api):
        """PRD §3.4: 'For APPOINTMENT, the system advances session_status
        from PENDING directly to ACCEPTED (no queue) and queue_position
        remains null.'

        Claim: APPOINTMENT mode consultation -> session_status ACCEPTED,
        queue_position null.
        """
        # An APPOINTMENT requires scheduled_start_at; we set a far-future
        # time to avoid OUT_OF_SCHEDULE on implementations that enforce
        # the doctor-schedule window. PRD does not commit to a publish
        # API for DoctorSchedule, so behavior outside the standard
        # workday hours is implementation-defined — we keep this test
        # at a noon-ish time that any reasonable schedule covers.
        from datetime import datetime, timedelta, timezone

        scheduled = (datetime.now(timezone.utc)
                     + timedelta(days=1)).replace(
            hour=12, minute=0, second=0, microsecond=0,
        )
        scheduled_iso = scheduled.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        state = setup_consultation_pending(
            mode="APPOINTMENT",
            scheduled_start_at=scheduled_iso,
            band="MID",
        )
        c = state["consultation"]
        assert c["session_status"] == "ACCEPTED"
        assert c.get("queue_position") is None


# =========================================================================
# Doctor matching: no eligible doctor.
# =========================================================================
class TestNoDoctorAvailable:

    def test_no_eligible_doctor_returns_422(self, api):
        """PRD §3.3: 'If the resulting candidate set is empty, the
        request is rejected with ERR_NO_DOCTOR_AVAILABLE.'

        Claim: when no doctor matches the recommended department,
        POST /consultations -> 422 ERR_NO_DOCTOR_AVAILABLE.
        """
        # Register a mapping pointing at department X, but create no
        # doctor in X. The patient's triage will recommend department X
        # (the only mapping), and the selector will find no doctors.
        register_department_mapping(
            department_code="ORPHAN_DEPT",
            disease_codes=[IN_SCOPE_DISEASE],
        )
        patient = create_patient()
        triage = open_and_assess_triage(
            patient=patient,
            responses=build_responses_for_band("MID"),
        )
        res = api.create_consultation(
            create_consultation_payload(
                triage_session_id=triage["id"],
                mode="REAL_TIME", media_type="TEXT_IMAGE",
            ),
            make_patient_headers(patient["id"]),
        )
        validate_error(res, ApiErrorId.ERR_NO_DOCTOR_AVAILABLE.value)


# =========================================================================
# Preferred doctor: pinned but ineligible.
# =========================================================================
class TestPreferredDoctorIneligible:

    def test_preferred_doctor_in_wrong_department_rejected(self, api):
        """PRD §3.3: 'When the patient supplies a preferred_doctor_id
        (either on the patient profile or in the create-consultation
        payload), the system skips the selector and instead verifies that
        the named doctor satisfies the eligibility filter described
        above. If the named doctor fails the filter, the request is
        rejected with ERR_PREFERRED_DOCTOR_INELIGIBLE -- the system does
        not silently fall back to the selector.'

        Claim: preferred_doctor_id points at a doctor whose
        department_code differs from triage's recommended_department_code
        -> 422 ERR_PREFERRED_DOCTOR_INELIGIBLE.
        """
        # Department CARDIO (default), with one CARDIO doctor (eligible
        # for triage). Then create a second doctor in DERM, mark him as
        # the patient's preferred_doctor_id.
        register_department_mapping(
            department_code=DEFAULT_DEPARTMENT_CODE,
            disease_codes=[IN_SCOPE_DISEASE],
        )
        register_department_mapping(
            department_code="DERM",
            disease_codes=["DERMA_X"],
            triage_priority=2,
        )
        # Eligible cardio doctor exists.
        create_doctor(
            department_code=DEFAULT_DEPARTMENT_CODE,
            specialty_codes=[IN_SCOPE_DISEASE],
            licensed_region_codes=[DEFAULT_REGION_CODE],
        )
        # Ineligible derm doctor.
        derm_doc = create_doctor(
            department_code="DERM",
            specialty_codes=["DERMA_X"],
            licensed_region_codes=[DEFAULT_REGION_CODE],
        )
        patient = create_patient(preferred_doctor_id=derm_doc["id"])
        triage = open_and_assess_triage(
            patient=patient,
            responses=build_responses_for_band("MID"),
        )
        res = api.create_consultation(
            create_consultation_payload(
                triage_session_id=triage["id"],
                mode="REAL_TIME", media_type="TEXT_IMAGE",
                doctor_id=derm_doc["id"],
            ),
            make_patient_headers(patient["id"]),
        )
        validate_error(res, ApiErrorId.ERR_PREFERRED_DOCTOR_INELIGIBLE.value)


# =========================================================================
# Consultation creation cascades TriageSession to MATCHED.
# =========================================================================
class TestTriageToMatchedOnConsultation:

    def test_triage_advances_to_matched(self, api):
        """PRD §3.3: 'Creating the consultation advances the parent
        triage from ASSESSED to MATCHED'.

        Claim: after POST /consultations, the parent TriageSession.status
        == MATCHED.
        """
        state = setup_consultation_pending(mode="REAL_TIME")
        from test_helpers import api_client, TEST_USERS, get_success_data
        refreshed = get_success_data(api_client.get_triage_session(
            state["triage"]["id"], TEST_USERS["platform_admin_headers"],
        ))
        assert refreshed["status"] == "MATCHED"
