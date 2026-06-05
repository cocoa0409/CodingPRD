"""Clinic appointments and peer-support sessions: half-open clinic overlap,
buffered counselor overlap, the serviceable-participant completion gate, the
no-show past-check, and OCC on clinic version (PRD §3.10, §3.11, §2.7).
"""
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    create_agency,
    create_clinic,
    create_household,
    create_participant,
    setup_clinic_with_appointment,
    setup_peer_session,
    setup_certified_participant,
    CLERK,
    CPA,
)


class TestClinicOverlap:
    def test_overlapping_appointment_collides(self, api):
        """PRD §3.10: "the candidate collides if the candidate's start is before
        the existing appointment's end and the existing appointment's start is
        before the candidate's end."
        PRD §3.10: "A collision is rejected with ERR_APPOINTMENT_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/clinic_appointment_half_open_overlap
        """
        ctx = setup_clinic_with_appointment(
            clock_iso=None, buffer_minutes=0,
            start_utc="2026-03-10T10:00:00.000Z", end_utc="2026-03-10T10:30:00.000Z",
        )
        clinic_v = ctx["clinic_version_after"]
        # [10:15,10:45) overlaps [10:00,10:30)
        resp = api.create_clinic_appointment(
            {
                "clinic_id": ctx["clinic"]["id"],
                "participant_id": ctx["participant"]["id"],
                "purpose": "NUTRITION_ED",
                "start_utc": "2026-03-10T10:15:00.000Z",
                "end_utc": "2026-03-10T10:45:00.000Z",
                "expected_clinic_version": clinic_v,
            },
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OVERLAP.value)

    def test_adjacent_appointment_touching_endpoint_allowed(self, api):
        """PRD §3.10: "The comparison is strict, so two intervals that merely touch
        at an endpoint — the candidate's start equal to an existing end, or the
        candidate's end equal to an existing start — do not collide and are
        allowed."

        Design: Difficulty/resource_temporal_overlap/clinic_appointment_half_open_overlap
        """
        ctx = setup_clinic_with_appointment(
            clock_iso=None, buffer_minutes=0,
            start_utc="2026-03-10T10:00:00.000Z", end_utc="2026-03-10T10:30:00.000Z",
        )
        clinic_v = ctx["clinic_version_after"]
        # [10:30,11:00) starts exactly where the first ends -> allowed
        appt = validate_success(api.create_clinic_appointment(
            {
                "clinic_id": ctx["clinic"]["id"],
                "participant_id": ctx["participant"]["id"],
                "purpose": "NUTRITION_ED",
                "start_utc": "2026-03-10T10:30:00.000Z",
                "end_utc": "2026-03-10T11:00:00.000Z",
                "expected_clinic_version": clinic_v,
            },
            CLERK,
        ), 201)
        assert appt["status"] == "SCHEDULED"


class TestPeerSessionOverlap:
    def test_session_within_buffer_collides(self, api):
        """PRD §3.11: "the server computes the gap in minutes between the two
        intervals (zero if they overlap at all), and the candidate collides if
        that gap is strictly less than the 15-minute travel buffer; a gap of
        exactly 15 minutes is allowed."
        PRD §3.11: "A collision is rejected with ERR_APPOINTMENT_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/peer_session_buffer_overlap
        """
        ctx = setup_peer_session(
            counselor_id="pc-1",
            start_utc="2026-03-10T10:00:00.000Z", end_utc="2026-03-10T10:30:00.000Z",
        )
        # second participant in same household, same counselor; gap 10:40-10:30 = 10 < 15
        hh_id = ctx["participant"]["household_id"]
        p2 = create_participant(hh_id, full_name="BF Two", ssn_last4="3002",
                                category="BREASTFEEDING", breastfeeding_opt_in=True)
        resp = api.create_peer_session(
            {
                "participant_id": p2["id"],
                "peer_counselor_id": "pc-1",
                "start_utc": "2026-03-10T10:40:00.000Z",
                "end_utc": "2026-03-10T11:00:00.000Z",
            },
            CPA,
        )
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_OVERLAP.value)

    def test_session_at_exactly_buffer_gap_allowed(self, api):
        """PRD §3.11: "a gap of exactly 15 minutes is allowed."

        Design: Difficulty/resource_temporal_overlap/peer_session_buffer_overlap
        """
        ctx = setup_peer_session(
            counselor_id="pc-2",
            start_utc="2026-03-10T10:00:00.000Z", end_utc="2026-03-10T10:30:00.000Z",
        )
        hh_id = ctx["participant"]["household_id"]
        p2 = create_participant(hh_id, full_name="BF Three", ssn_last4="3003",
                                category="BREASTFEEDING", breastfeeding_opt_in=True)
        # gap 10:45-10:30 = exactly 15 -> allowed
        session = validate_success(api.create_peer_session(
            {
                "participant_id": p2["id"],
                "peer_counselor_id": "pc-2",
                "start_utc": "2026-03-10T10:45:00.000Z",
                "end_utc": "2026-03-10T11:15:00.000Z",
            },
            CPA,
        ), 201)
        assert session["status"] == "SCHEDULED"


class TestAppointmentGates:
    def test_complete_terminated_participant_rejected(self, api):
        """PRD §3.10: "A CPA completes a SCHEDULED appointment (otherwise
        ERR_INVALID_STATE), but only when the participant being seen is currently
        in APPLICANT or ACTIVE status; a participant in any other status causes the
        completion to be rejected with ERR_PARTICIPANT_NOT_SERVICEABLE."

        Design: Difficulty/cross_entity_state_dependency/complete_appointment_requires_serviceable_participant
        """
        # Certify a participant, schedule an appointment, then terminate the cert
        # so the participant becomes TERMINATED, then attempt completion.
        ctx = setup_certified_participant(
            category="PREGNANT", adjunctive_program="MEDICAID",
            household_size=2, pregnancy_count=1, risk_factor_codes=["GEST_DIABETES"],
            income_records=[(150000, "MONTHLY")],
            clock_iso="2026-03-02T00:00:00.000Z", ssn_last4="2009",
        )
        agency_id = ctx["agency_id"]
        p_id = ctx["participant"]["id"]
        clinic = create_clinic(agency_id, appointment_buffer_minutes=0)
        clinic_v = validate_success(api.get_clinic(clinic["id"], CLERK))["version"]
        appt = validate_success(api.create_clinic_appointment(
            {
                "clinic_id": clinic["id"],
                "participant_id": p_id,
                "purpose": "INITIAL_CERT",
                "start_utc": "2026-03-10T10:00:00.000Z",
                "end_utc": "2026-03-10T10:30:00.000Z",
                "expected_clinic_version": clinic_v,
            },
            CLERK,
        ), 201)
        validate_success(api.terminate_certification(ctx["certification"]["id"], CPA))
        resp = api.complete_clinic_appointment(appt["id"], CPA)
        validate_error(resp, ApiErrorId.ERR_PARTICIPANT_NOT_SERVICEABLE.value)

    def test_complete_applicant_participant_succeeds(self, api):
        """PRD §3.10: "A CPA completes a SCHEDULED appointment (otherwise
        ERR_INVALID_STATE), but only when the participant being seen is currently
        in APPLICANT or ACTIVE status; a participant in any other status causes the
        completion to be rejected with ERR_PARTICIPANT_NOT_SERVICEABLE. Completion
        moves the appointment to COMPLETED."

        The serviceable side of the cross-entity gate: an APPLICANT participant is
        serviceable, so completion is permitted and the appointment becomes
        COMPLETED.

        Design: Difficulty/cross_entity_state_dependency/complete_appointment_requires_serviceable_participant
        """
        # Fresh participant defaults to APPLICANT status (serviceable).
        ctx = setup_clinic_with_appointment(
            clock_iso="2026-03-02T00:00:00.000Z", buffer_minutes=0,
            start_utc="2026-03-10T10:00:00.000Z", end_utc="2026-03-10T10:30:00.000Z",
            category="CHILD",
        )
        participant = validate_success(api.get_participant(ctx["participant"]["id"], CPA))
        assert participant["status"] == "APPLICANT"
        appt = validate_success(api.complete_clinic_appointment(ctx["appointment"]["id"], CPA))
        assert appt["status"] == "COMPLETED"

    def test_no_show_before_appointment_past_rejected(self, api):
        """PRD §3.10: "A clerk marks a SCHEDULED appointment as a no-show — moving
        it to NO_SHOW — but only once it is in the past, meaning the agency's
        current_utc has reached or passed the appointment's end_utc; an attempt
        before that point is rejected with ERR_APPOINTMENT_NOT_PAST."

        Design: Corner/state_machines/no_show_before_appointment_past_rejected
        """
        ctx = setup_clinic_with_appointment(
            clock_iso="2026-03-01T00:00:00.000Z", buffer_minutes=0,
            start_utc="2026-03-10T10:00:00.000Z", end_utc="2026-03-10T10:30:00.000Z",
        )
        # clock is 2026-03-01, before the appointment end
        resp = api.no_show_clinic_appointment(ctx["appointment"]["id"], CLERK)
        validate_error(resp, ApiErrorId.ERR_APPOINTMENT_NOT_PAST.value)


def test_stale_clinic_version_on_appointment_rejected(api):
    """PRD §2.7: "Scheduling a clinic appointment requires expected_clinic_version
    in the request body, carrying the client's last observed version of the target
    Clinic."
    PRD §2.7: "If expected_clinic_version does not match the clinic's current
    version, the request is rejected with ERR_STALE_VERSION (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_clinic_version_on_appointment
    """
    agency = create_agency()
    clinic = create_clinic(agency["id"], appointment_buffer_minutes=0)
    hh = create_household(agency["id"], household_size=3, adjunctive_program="SNAP")
    p = create_participant(hh["id"], full_name="OCC Kid", ssn_last4="1414", category="CHILD")
    clinic_ver_pre = validate_success(api.get_clinic(clinic["id"], CLERK))["version"]
    # first appointment bumps clinic.version
    validate_success(api.create_clinic_appointment(
        {
            "clinic_id": clinic["id"],
            "participant_id": p["id"],
            "purpose": "INITIAL_CERT",
            "start_utc": "2026-03-10T09:00:00.000Z",
            "end_utc": "2026-03-10T09:30:00.000Z",
            "expected_clinic_version": clinic_ver_pre,
        },
        CLERK,
    ), 201)
    # second appointment reuses the stale pre-advance clinic version
    resp = api.create_clinic_appointment(
        {
            "clinic_id": clinic["id"],
            "participant_id": p["id"],
            "purpose": "NUTRITION_ED",
            "start_utc": "2026-03-10T11:00:00.000Z",
            "end_utc": "2026-03-10T11:30:00.000Z",
            "expected_clinic_version": clinic_ver_pre,
        },
        CLERK,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value)
