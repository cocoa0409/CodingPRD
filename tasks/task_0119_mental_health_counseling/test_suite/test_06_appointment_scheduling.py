"""Appointment scheduling — collisions, time-range validation, check-in
window, hold/unhold lifecycle.

PRD §3.6 (scheduling, holds, check-in).
"""
from __future__ import annotations

import pytest

from test_helpers import (
    PATIENT_MIN_GAP_MINUTES,
    TEST_USERS,
    advance_clock_to,
    anchor_clock,
    assert_appointment,
    checkin_appointment,
    create_appointment_payload,
    create_patient,
    create_session,
    iso_anchor_offset,
    make_therapist_headers,
    re_get_appointment,
    schedule_appointment,
    setup_active_licensed_therapist,
    setup_checked_in_appointment,
    setup_scheduled_appointment,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.6 Create + time-range
# ===========================================================================
class TestAppointmentCreate:

    def test_create_appointment_initial_state(self, api):
        """PRD §3.6: "The appointment is born in status = SCHEDULED
        with hold_reason left null."

        Claim: a freshly-created Appointment has status=SCHEDULED and
        hold_reason=null.
        """
        bundle = setup_scheduled_appointment()
        data = bundle["appointment"]
        assert_appointment(data)
        assert data["status"] == "SCHEDULED"
        assert data.get("hold_reason") is None

    def test_scheduled_end_before_start_rejected(self, api):
        """PRD §3.6: "scheduled_end must be strictly after
        scheduled_start and the minimum session length is one minute;
        violations return ERR_INVALID_TIMERANGE."

        Claim: scheduled_end < scheduled_start returns
        ERR_INVALID_TIMERANGE.
        """
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist()
        patient = create_patient(state_of_residence="NY")
        payload = create_appointment_payload(
            therapist_id=therapist["id"], patient_id=patient["id"],
            scheduled_start=iso_anchor_offset(hours=2, minutes=45),
            scheduled_end=iso_anchor_offset(hours=2),
        )
        res = api.create_appointment(
            payload, make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_INVALID_TIMERANGE")

    def test_zero_length_session_rejected(self, api):
        """PRD §3.6: "scheduled_end must be strictly after
        scheduled_start and the minimum session length is one minute;
        violations return ERR_INVALID_TIMERANGE."

        Claim: scheduled_end == scheduled_start returns
        ERR_INVALID_TIMERANGE.
        """
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist()
        patient = create_patient(state_of_residence="NY")
        ts = iso_anchor_offset(hours=2)
        payload = create_appointment_payload(
            therapist_id=therapist["id"], patient_id=patient["id"],
            scheduled_start=ts, scheduled_end=ts,
        )
        res = api.create_appointment(
            payload, make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_INVALID_TIMERANGE")


# ===========================================================================
# §3.6 Collision rules
# ===========================================================================
class TestSchedulingCollisions:

    def test_therapist_overlap_rejected(self, api):
        """PRD §3.6: "The proposed window must not overlap any existing
        appointment for the same therapist whose status is one of
        SCHEDULED, HELD, or CHECKED_IN ... Violations are rejected with
        ERR_THERAPIST_DOUBLE_BOOKED."

        Claim: a second appointment overlapping the first for the same
        therapist returns ERR_THERAPIST_DOUBLE_BOOKED.
        """
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist()
        p1 = create_patient(state_of_residence="NY", full_name="P1")
        p2 = create_patient(state_of_residence="NY", full_name="P2")
        schedule_appointment(
            therapist["id"], p1["id"],
            scheduled_start=iso_anchor_offset(hours=23),
            scheduled_end=iso_anchor_offset(hours=24),
        )
        overlap = create_appointment_payload(
            therapist_id=therapist["id"], patient_id=p2["id"],
            scheduled_start=iso_anchor_offset(hours=23, minutes=30),
            scheduled_end=iso_anchor_offset(hours=24, minutes=30),
        )
        res = api.create_appointment(
            overlap, make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_THERAPIST_DOUBLE_BOOKED")

    def test_therapist_back_to_back_allowed(self, api):
        """PRD §3.6: "where overlap is computed under half-open
        [scheduled_start, scheduled_end) semantics — so back-to-back
        appointments whose former's scheduled_end exactly equals the
        latter's scheduled_start are explicitly allowed."

        Claim: two appointments adjacent at second.scheduled_start ==
        first.scheduled_end (for the same therapist, different
        patients) are both accepted.
        """
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist()
        p1 = create_patient(state_of_residence="NY", full_name="P1")
        p2 = create_patient(state_of_residence="NY", full_name="P2")
        schedule_appointment(
            therapist["id"], p1["id"],
            scheduled_start=iso_anchor_offset(hours=23),
            scheduled_end=iso_anchor_offset(hours=24),
        )
        adj = create_appointment_payload(
            therapist_id=therapist["id"], patient_id=p2["id"],
            scheduled_start=iso_anchor_offset(hours=24),
            scheduled_end=iso_anchor_offset(hours=25),
        )
        res = api.create_appointment(
            adj, make_therapist_headers(therapist["id"]),
        )
        validate_success(res, expected_status=201)

    def test_patient_zero_gap_rejected(self, api):
        """PRD §3.6: "The proposed window must also leave a minimum
        gap of five minutes from any existing appointment for the same
        patient ... Zero-gap adjacency for the same patient is rejected
        with ERR_PATIENT_DOUBLE_BOOKED."

        Claim: scheduling two back-to-back appointments for the same
        patient (zero-minute gap) on two different therapists returns
        ERR_PATIENT_DOUBLE_BOOKED.
        """
        anchor_clock()
        t1, _ = setup_active_licensed_therapist()
        t2, _ = setup_active_licensed_therapist()
        patient = create_patient(state_of_residence="NY")
        schedule_appointment(
            t1["id"], patient["id"],
            scheduled_start=iso_anchor_offset(hours=23),
            scheduled_end=iso_anchor_offset(hours=24),
        )
        adj = create_appointment_payload(
            therapist_id=t2["id"], patient_id=patient["id"],
            scheduled_start=iso_anchor_offset(hours=24),
            scheduled_end=iso_anchor_offset(hours=25),
        )
        res = api.create_appointment(
            adj, make_therapist_headers(t2["id"]),
        )
        validate_error(res, "ERR_PATIENT_DOUBLE_BOOKED")

    def test_patient_five_minute_gap_allowed(self, api):
        """PRD §3.6: "either the new appointment's scheduled_start
        minus the other's scheduled_end is at least five minutes, or
        the other's scheduled_start minus the new appointment's
        scheduled_end is at least five minutes."

        Claim: scheduling a second appointment for the same patient
        exactly 5 minutes after the first ends is accepted.
        """
        assert PATIENT_MIN_GAP_MINUTES == 5
        anchor_clock()
        t1, _ = setup_active_licensed_therapist()
        t2, _ = setup_active_licensed_therapist()
        patient = create_patient(state_of_residence="NY")
        schedule_appointment(
            t1["id"], patient["id"],
            scheduled_start=iso_anchor_offset(hours=23),
            scheduled_end=iso_anchor_offset(hours=24),
        )
        adj = create_appointment_payload(
            therapist_id=t2["id"], patient_id=patient["id"],
            scheduled_start=iso_anchor_offset(hours=24, minutes=5),
            scheduled_end=iso_anchor_offset(hours=25, minutes=5),
        )
        res = api.create_appointment(
            adj, make_therapist_headers(t2["id"]),
        )
        validate_success(res, expected_status=201)


# ===========================================================================
# §3.6 Check-in window
# ===========================================================================
class TestCheckInWindow:

    def test_checkin_too_early_rejected(self, api):
        """PRD §3.6: "The check-in is admitted only when the current
        clock is within the window [scheduled_start − 15min,
        scheduled_start + 30min]; outside this window the request is
        rejected with ERR_OUTSIDE_CHECKIN_WINDOW."

        Claim: a check-in attempted strictly more than 15 minutes
        before scheduled_start returns ERR_OUTSIDE_CHECKIN_WINDOW.
        """
        bundle = setup_scheduled_appointment(
            minutes_after_anchor_start=120,
        )
        # Anchor clock is at +0; appointment at +120 min;
        # window starts at +105 min. We're at +0, so well outside.
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_OUTSIDE_CHECKIN_WINDOW")

    def test_checkin_too_late_rejected(self, api):
        """PRD §3.6: "The check-in is admitted only when the current
        clock is within the window [scheduled_start − 15min,
        scheduled_start + 30min]; outside this window the request is
        rejected with ERR_OUTSIDE_CHECKIN_WINDOW."

        Claim: a check-in attempted strictly more than 30 minutes
        after scheduled_start returns ERR_OUTSIDE_CHECKIN_WINDOW.
        """
        bundle = setup_scheduled_appointment(
            minutes_after_anchor_start=120,
        )
        # Move past +30 minutes after start (+150 min anchor offset).
        advance_clock_to(iso_anchor_offset(minutes=120 + 31))
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        validate_error(res, "ERR_OUTSIDE_CHECKIN_WINDOW")

    def test_checkin_inside_window_succeeds(self, api):
        """PRD §3.6: "When all checks pass, the appointment transitions
        from SCHEDULED to CHECKED_IN."

        Claim: a check-in inside the window transitions the
        appointment to CHECKED_IN.
        """
        bundle = setup_checked_in_appointment(
            minutes_after_anchor_start=120,
        )
        assert bundle["appointment"]["status"] == "CHECKED_IN"


# ===========================================================================
# §3.6 Hold / unhold / cancel
# ===========================================================================
class TestHoldLifecycle:

    def test_cancel_held_appointment_clears_hold_reason(self, api):
        """PRD §3.6: "A SCHEDULED or HELD appointment may be cancelled
        by the acting therapist or by an administrator at any moment
        strictly before scheduled_start; the transition takes the
        appointment to CANCELLED and clears hold_reason to null when
        the source state was HELD."

        Claim: cancelling a HELD appointment transitions to CANCELLED
        and clears hold_reason to null.
        """
        bundle = setup_scheduled_appointment(
            minutes_after_anchor_start=120,
        )
        # Suspend therapist -> appointment goes to HELD.
        from test_helpers import suspend_therapist
        suspend_therapist(bundle["therapist"]["id"])
        appt = re_get_appointment(bundle["appointment"]["id"])
        assert appt["status"] == "HELD"
        assert appt["hold_reason"] == "LICENSE_GAP"
        # Cancel as PracticeAdmin (allowed per §3.6).
        res = api.cancel_appointment(
            appt["id"], TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CANCELLED"
        assert data.get("hold_reason") is None

    def test_cancel_scheduled_appointment_succeeds(self, api):
        """PRD §3.6: "A SCHEDULED or HELD appointment may be cancelled
        ... at any moment strictly before scheduled_start; the
        transition takes the appointment to CANCELLED ..."

        Claim: cancelling a SCHEDULED appointment before
        scheduled_start succeeds.
        """
        bundle = setup_scheduled_appointment(
            minutes_after_anchor_start=120,
        )
        res = api.cancel_appointment(
            bundle["appointment"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CANCELLED"

    def test_mark_no_show_after_end_succeeds(self, api):
        """PRD §3.6: "A SCHEDULED appointment that the patient never
        attended may be marked as a no-show after scheduled_end has
        passed; the transition takes the appointment to NO_SHOW."

        Claim: after the clock advances past scheduled_end, mark-no-show
        transitions the SCHEDULED appointment to NO_SHOW.
        """
        bundle = setup_scheduled_appointment(
            minutes_after_anchor_start=120,
            duration_minutes=45,
        )
        # Advance past scheduled_end (120 + 45 = 165m).
        advance_clock_to(iso_anchor_offset(minutes=166))
        res = api.mark_no_show_appointment(
            bundle["appointment"]["id"],
            TEST_USERS["practice_admin_headers"],
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "NO_SHOW"


# ===========================================================================
# §3.6 Cross-state license + PSYPACT
# ===========================================================================
class TestLicenseCoverageAtCheckIn:

    def test_checkin_without_state_license_rejected(self, api):
        """PRD §3.6: "The therapist must hold an ACTIVE StateLicense
        whose state_code equals patient_state_on_day, or — for
        telehealth coverage under the interstate compact — the
        therapist must have psypact_enrolled = true ... Failure of the
        license coverage check is rejected with ERR_LICENSE_GAP_FOR_STATE."

        Claim: a check-in for a NY appointment by a therapist holding
        only a CA license (psypact_enrolled=false) returns
        ERR_LICENSE_GAP_FOR_STATE.
        """
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist(state_code="CA")
        patient = create_patient(state_of_residence="NY")
        appt = schedule_appointment(
            therapist["id"], patient["id"],
            cpt_code="90834", modality="TELEHEALTH",
            patient_state_on_day="NY",
            scheduled_start=iso_anchor_offset(hours=2),
            scheduled_end=iso_anchor_offset(hours=2, minutes=45),
        )
        advance_clock_to(iso_anchor_offset(hours=1, minutes=59))
        res = api.checkin_appointment(
            appt["id"], make_therapist_headers(therapist["id"]),
        )
        validate_error(res, "ERR_LICENSE_GAP_FOR_STATE")

    def test_checkin_with_psypact_compact_succeeds(self, api):
        """PRD §3.6: "for telehealth coverage under the interstate
        compact — the therapist must have psypact_enrolled = true,
        patient_state_on_day must be a PSYPACT-participating state, and
        the therapist must hold at least one ACTIVE license whose
        state_code is itself a PSYPACT-participating state."

        Claim: a psypact_enrolled therapist holding an ACTIVE PSYPACT
        state license (CO) checks in for a telehealth appointment whose
        patient_state_on_day is another PSYPACT state (TX).
        """
        anchor_clock()
        therapist, _ = setup_active_licensed_therapist(
            state_code="CO", psypact_enrolled=True,
        )
        patient = create_patient(state_of_residence="TX")
        appt = schedule_appointment(
            therapist["id"], patient["id"],
            cpt_code="90834", modality="TELEHEALTH",
            patient_state_on_day="TX",
            scheduled_start=iso_anchor_offset(hours=2),
            scheduled_end=iso_anchor_offset(hours=2, minutes=45),
        )
        advance_clock_to(iso_anchor_offset(hours=1, minutes=59))
        res = api.checkin_appointment(
            appt["id"], make_therapist_headers(therapist["id"]),
        )
        data = validate_success(res, expected_status=200)
        assert data["status"] == "CHECKED_IN"


# ===========================================================================
# §3.6 Therapist credential check at check-in
# ===========================================================================
class TestCredentialAtCheckIn:

    def test_checkin_with_suspended_therapist_rejected(self, api):
        """PRD §3.6: "The acting therapist's credential_status must be
        one of PROVISIONAL or ACTIVE (pre-licensed associates may see
        patients while accruing supervised hours; SUSPENDED and
        DEACTIVATED are rejected with ERR_THERAPIST_NOT_ACTIVE)."

        Claim: a check-in attempt by a SUSPENDED therapist is rejected.
        Note: a suspension cascade ALSO HOLDs the appointment, so the
        appointment-state check at priority 7 (ERR_APPT_NOT_OPEN) may
        actually fire first; either is acceptable.
        """
        bundle = setup_scheduled_appointment(
            minutes_after_anchor_start=120,
        )
        from test_helpers import suspend_therapist
        suspend_therapist(bundle["therapist"]["id"])
        advance_clock_to(iso_anchor_offset(minutes=119))
        res = api.checkin_appointment(
            bundle["appointment"]["id"],
            make_therapist_headers(bundle["therapist"]["id"]),
        )
        # PRD §2.7 pipeline: state precondition (priority 7) fires
        # before referential checks; the HELD cascade leaves the
        # appointment in HELD, so ERR_APPT_NOT_OPEN is the deterministic
        # outcome. ERR_THERAPIST_NOT_ACTIVE is also faithful to PRD if
        # an implementation evaluates referential before state — accept
        # either.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res, ["ERR_APPT_NOT_OPEN", "ERR_THERAPIST_NOT_ACTIVE"],
        )
