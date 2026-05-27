"""State-machine corners: initial state, invalid transition,
terminal-state lockdown, idempotency, and AnnualResetRun temporal gate."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    set_clock,
    create_property,
    create_member,
    record_gaming_session,
    get_member_version,
    create_booking,
    confirm_booking,
    cancel_booking_as_manager,
    schedule_annual_reset,
    ApiErrorId,
    make_loyalty_manager_headers,
    make_compliance_officer_headers,
    bootstrap_platinum_with_pending_booking,
    bootstrap_platinum_with_completed_booking,
)


class TestCompRoomBookingInitialStateIsPending:
    """PRD §3.6: a freshly-created CompRoomBooking starts in PENDING."""

    def test_create_booking_returns_pending(self, api):
        """PRD §3.6: "The booking is created in status PENDING with version
        1 and final_rate_cents null".

        Design: Corner/state_machines/comp_room_booking_initial_state_is_pending
        """
        ctx = bootstrap_platinum_with_pending_booking(
            clock="2026-02-15T00:00:00Z",
            check_in="2026-03-15T15:00:00Z",
            check_out="2026-03-16T11:00:00Z",
        )
        assert ctx["booking"]["status"] == "PENDING"


class TestCompRoomBookingInvalidTransitionFromPending:
    """PRD §3.6: /check-in is permitted only from CONFIRMED. From PENDING
    it must fail with ERR_INVALID_STATE."""

    def test_check_in_from_pending_returns_invalid_state(self, api):
        """PRD §3.6: "Check-in transitions the booking CONFIRMED →
        CHECKED_IN, but only once the server's current UTC clock is at or
        past the booking's check_in, and only if the member is not
        excluded and not velocity-suspended."

        Design: Corner/state_machines/comp_room_booking_check_in_from_pending_invalid_transition
        """
        ctx = bootstrap_platinum_with_pending_booking(
            clock="2026-02-20T00:00:00Z",
            check_in="2026-03-20T15:00:00Z",
            check_out="2026-03-21T11:00:00Z",
        )
        # Attempt /check-in on a PENDING booking.
        resp = api.check_in_comp_room_booking(
            ctx["booking"]["id"], make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestCompRoomBookingTerminalLockdown:
    """PRD §3.6 + §3.9: COMPLETED is terminal — cancel must fail."""

    def test_completed_booking_cannot_be_cancelled(self, api):
        """PRD §3.6: "Cancellation transitions the booking from either
        PENDING or CONFIRMED to CANCELLED and may be initiated by a
        LoyaltyManager, by the member themselves on their own bookings,
        or by the system as a cascade from a member self-exclusion or a
        velocity suspension."

        A COMPLETED booking is outside both PENDING and CONFIRMED, so the
        only legitimate observable is the state-eligibility rejection
        (ERR_INVALID_STATE).

        Design: Corner/state_machines/comp_room_booking_terminal_completed_cannot_be_cancelled
        """
        ctx = bootstrap_platinum_with_completed_booking(
            clock="2026-03-01T00:00:00Z",
            check_in="2026-04-01T15:00:00Z",
            check_out="2026-04-02T11:00:00Z",
            post_check_in_clock="2026-04-01T16:00:00Z",
            post_check_out_clock="2026-04-02T12:00:00Z",
        )
        assert ctx["booking"]["status"] == "COMPLETED"
        resp = api.cancel_comp_room_booking(
            ctx["booking"]["id"], make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestCancelAlreadyCancelledIsRejected:
    """PRD §3.6: cancellation moves PENDING/CONFIRMED to CANCELLED. A
    repeat /cancel on a CANCELLED booking is not in the allowed source
    states — ERR_INVALID_STATE."""

    def test_cancel_twice_returns_invalid_state(self, api):
        """PRD §3.6: "Cancellation transitions the booking from either
        PENDING or CONFIRMED to CANCELLED and may be initiated by a
        LoyaltyManager, by the member themselves on their own bookings,
        or by the system as a cascade from a member self-exclusion or a
        velocity suspension."

        Design: Corner/state_machines/cancel_booking_from_already_cancelled_returns_invalid_state
        """
        set_clock("2026-03-05T00:00:00Z")
        prop = create_property()
        mem = create_member(
            property_id=prop["id"], full_name="C1", email="c1@x.com",
        )
        v = get_member_version(mem["id"])
        booking = create_booking(
            member_id=mem["id"], property_id=prop["id"],
            expected_member_version=v,
            check_in="2026-04-05T15:00:00Z",
            check_out="2026-04-06T11:00:00Z",
        )
        cancel_booking_as_manager(booking["id"])
        resp = api.cancel_comp_room_booking(
            booking["id"], make_loyalty_manager_headers("lm_1"),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestAnnualResetExecuteBeforeDue:
    """PRD §3.8: /execute is permitted only once the clock has reached or
    surpassed scheduled_for."""

    def test_execute_before_scheduled_for_returns_reset_not_due(self, api):
        """PRD §3.8: "Executing the run is permitted only once the
        server's current UTC clock has reached or surpassed scheduled_for;
        an earlier attempt fails with ERR_RESET_NOT_DUE."

        Design: Corner/state_machines/annual_reset_execute_before_due_returns_reset_not_due
        """
        set_clock("2027-06-01T00:00:00Z")
        ar = schedule_annual_reset(
            reset_year=2027, scheduled_for="2028-01-01T00:00:00Z",
        )
        resp = api.execute_annual_reset_run(
            ar["id"], make_compliance_officer_headers("co_1"),
        )
        validate_error(resp, ApiErrorId.ERR_RESET_NOT_DUE.value)
