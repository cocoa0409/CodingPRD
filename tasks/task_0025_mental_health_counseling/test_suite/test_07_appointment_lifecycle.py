"""Reschedule, start, complete, and no-show transitions (PRD §3.5)."""
from __future__ import annotations
import pytest

from test_helpers import (
    advance_clock,
    api_client,
    bring_counselor_to_active,
    cancel_appointment,
    confirm_appointment,
    create_appointment_in_hold,
    create_counseling_record,
    create_slot,
    DEFAULT_T0,
    get_appointment,
    get_client,
    make_admin_headers,
    make_client_headers,
    make_counselor_headers,
    parse_iso,
    iso_z,
    reschedule_appointment,
    reschedule_appointment_payload,
    setup_confirmed_appointment,
    setup_counselor_and_completed_client,
    shift,
    start_appointment,
    sweep_no_show,
    validate_error,
    validate_success,
)


class TestStartAndComplete:
    def test_start_within_window_sets_started_at(self):
        """PRD §3.5: "Starting the session is a counselor action. The
        transition from `CONFIRMED` to `IN_SESSION` is admitted only while
        current time is at or after `start_at` minus five minutes and
        strictly before `start_at` plus fifteen minutes, and only while the
        counselor is `ACTIVE`; on success `started_at` is set to current
        time."
        """
        counselor, client, slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
        )
        # Anchor clock at slot.start_at - 4 minutes (within [-5, +15) window).
        advance_clock(shift(slot["start_at"], minutes=-4))
        started = start_appointment(counselor, confirmed)
        assert started["status"] == "IN_SESSION"
        assert started["started_at"] is not None

    def test_start_outside_window_rejected(self, api):
        """PRD §3.5: "is admitted only while current time is at or after
        `start_at` minus five minutes and strictly before `start_at` plus
        fifteen minutes..."
        """
        counselor, client, slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
        )
        # Anchor clock at start_at - 10 min (before -5m window).
        advance_clock(shift(slot["start_at"], minutes=-10))
        res = api.start_appointment(
            confirmed["id"], make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_complete_without_record_rejected(self, api):
        """PRD §3.5: "Completing the session is also a counselor action.
        The transition from `IN_SESSION` to `COMPLETED` is permitted only
        when a CounselingRecord already exists for this `appointment_id`
        (otherwise the implicit completion gate triggers `ERR_INVALID_STATE`)."
        """
        counselor, client, slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
        )
        advance_clock(shift(slot["start_at"], minutes=-4))
        started = start_appointment(counselor, confirmed)
        # Try to complete WITHOUT creating the counseling record first.
        res = api.complete_appointment(
            started["id"], make_counselor_headers(counselor["id"]),
        )
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    def test_complete_with_record_succeeds(self, api):
        """PRD §3.5: "On completion, `ended_at` is set to current time, and
        if `assessment_status` was `IN_PROGRESS` and `appointment_type` was
        `INTAKE`, `assessment_status` flips to `COMPLETED`."
        """
        advance_clock(DEFAULT_T0)
        counselor = bring_counselor_to_active()
        client = get_client.__wrapped__ if hasattr(get_client, "__wrapped__") else None
        # Walk client through INTAKE -> CONFIRMED -> IN_SESSION -> COMPLETED.
        from test_helpers import create_client
        client = create_client()
        intake_start = shift(DEFAULT_T0, hours=200)
        slot = create_slot(counselor=counselor, start_at=intake_start)
        appt = create_appointment_in_hold(
            counselor=counselor, client=client, slot=slot,
            appointment_type="INTAKE", payment_mode="PAY_PER_SESSION",
        )
        confirmed = confirm_appointment(client, appt)
        advance_clock(shift(intake_start, minutes=-4))
        started = start_appointment(counselor, confirmed)
        create_counseling_record(
            counselor=counselor, appointment=started,
            encrypted_note_blob="aW50YWtlLW5vdGUtY2lwaGVydGV4dA==",
        )
        res = api.complete_appointment(
            started["id"], make_counselor_headers(counselor["id"]),
        )
        completed = validate_success(res, expected_status=200)
        assert completed["status"] == "COMPLETED"
        assert completed["ended_at"] is not None
        # PRD §3.5: assessment_status flips IN_PROGRESS -> COMPLETED for INTAKE.
        client_after = get_client(client["id"])
        assert client_after["assessment_status"] == "COMPLETED"


class TestNoShowSweep:
    def test_no_show_sweep_marks_appointment(self):
        """PRD §3.5: "If the counselor never starts and current time
        advances to at least `start_at` plus thirty minutes while still
        `CONFIRMED`, the no-show sweep moves the appointment to `NO_SHOW`
        with `cancellation_reason` of `NO_SHOW_AUTO`, sets `refund_state` to
        `NON_REFUNDABLE`, and releases the slot."
        """
        counselor, client, slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
        )
        advance_clock(shift(slot["start_at"], minutes=31))
        sweep_no_show()
        appt_after = get_appointment(confirmed["id"])
        assert appt_after["status"] == "NO_SHOW"
        assert appt_after["cancellation_reason"] == "NO_SHOW_AUTO"
        assert appt_after["refund_state"] == "NON_REFUNDABLE"


class TestReschedule:
    def test_reschedule_within_24h_rejected(self, api):
        """PRD §3.5: "Rescheduling is performed by either the `Client` or
        the owning `Counselor` and is admitted only while current time is
        strictly less than the appointment's confirmed `start_at` minus
        twenty-four hours; closer than that, the request is rejected with
        `ERR_RESCHEDULE_WINDOW_CLOSED`."
        """
        counselor, client, slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
        )
        # Advance so now() > start_at - 24h.
        advance_clock(shift(slot["start_at"], hours=-23))
        # Need a new slot for the reschedule attempt (it must exist).
        new_slot = create_slot(
            counselor=counselor, start_at=shift(slot["start_at"], hours=48),
        )
        res = api.reschedule_appointment(
            confirmed["id"],
            reschedule_appointment_payload(new_slot_id=new_slot["id"]),
            make_client_headers(client["id"]),
        )
        validate_error(res, "ERR_RESCHEDULE_WINDOW_CLOSED", expected_status=409)


class TestCounselorActiveGate:
    def test_start_after_counselor_disqualified_rejected(self, api):
        """PRD §3.5: "the transition from `CONFIRMED` to `IN_SESSION` is
        admitted only while ... the counselor is `ACTIVE`..."
        """
        counselor, client, slot, confirmed = setup_confirmed_appointment(
            start_offset_hours=30, payment_mode="PAY_PER_SESSION",
        )
        from test_helpers import disqualify_counselor as dq
        dq(counselor)
        # Counselor is now DISQUALIFIED. Attempt to start.
        advance_clock(shift(slot["start_at"], minutes=-4))
        res = api.start_appointment(
            confirmed["id"], make_counselor_headers(counselor["id"]),
        )
        # Error can be ERR_INVALID_STATE (because cascade may have CANCELLED
        # the appointment) or ERR_COUNSELOR_NOT_ACTIVE (PRD §2.7: counselor-
        # active gate is priority 6, before state). PRD §3.2 disqualify
        # cascades CONFIRMED future appointments to CANCELLED, so the
        # appointment is no longer in CONFIRMED. Either is faithful.
        from test_helpers import validate_error_is_one_of
        validate_error_is_one_of(
            res, ["ERR_COUNSELOR_NOT_ACTIVE", "ERR_INVALID_STATE"],
        )
