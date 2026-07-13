"""Conservation of booking minutes and session seats across a create+cancel pair
(PRD §2.5, §3.9)."""
from test_helpers import (
    TEST_USERS,
    setup_scheduled_flight,
    validate_success,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


class TestBookingMinuteConservation:
    """Create-flight then cancel-flight leaves the minute pool undrifted."""

    def _setup(self, api):
        ctx = setup_scheduled_flight(
            api,
            booking_kw={"party_size": 2},
            scheduled_minutes=2,
            sign_waiver=False,
            start=False,
        )
        validate_success(api.cancel_flight(ctx["flight"]["id"], FRONTDESK), 200)
        return ctx

    def test_minutes_remaining_restored(self, api):
        """PRD §2.5: "For any booking, `minutes_remaining` plus the minutes consumed by
        its active flights always equals `minutes_included`; every refund exactly
        restores what a flight consumed."
        PRD §3.9: "The flight's `scheduled_minutes` are refunded to its booking, raising
        `minutes_remaining`, and the session seat is released, decrementing
        `seats_taken`."

        Design: Difficulty/compensating_invariant/booking_minutes_conserved_on_flight_cancel
        """
        ctx = self._setup(api)
        booking = validate_success(api.get_booking(ctx["booking"]["id"], FRONTDESK), 200)
        assert booking["minutes_remaining"] == 4, booking["minutes_remaining"]

    def test_minutes_included_unchanged(self, api):
        """PRD §2.5: "For any booking, `minutes_remaining` plus the minutes consumed by
        its active flights always equals `minutes_included`; every refund exactly
        restores what a flight consumed."

        Design: Difficulty/compensating_invariant/booking_minutes_conserved_on_flight_cancel
        """
        ctx = self._setup(api)
        booking = validate_success(api.get_booking(ctx["booking"]["id"], FRONTDESK), 200)
        assert booking["minutes_included"] == 4, booking["minutes_included"]


class TestSessionSeatConservation:
    """Create-flight then cancel-flight leaves the seat count undrifted."""

    def _setup(self, api):
        ctx = setup_scheduled_flight(
            api,
            booking_kw={"party_size": 1},
            session_kw={"capacity": 4},
            scheduled_minutes=2,
            sign_waiver=False,
            start=False,
        )
        validate_success(api.cancel_flight(ctx["flight"]["id"], FRONTDESK), 200)
        return ctx

    def test_seats_taken_restored(self, api):
        """PRD §2.5: "For any session, `seats_taken` plus `seats_available` always
        equals `capacity`; every seat released exactly offsets a seat taken."
        PRD §3.9: "the session seat is released, decrementing `seats_taken`."

        Design: Difficulty/compensating_invariant/session_seats_conserved_on_flight_cancel
        """
        ctx = self._setup(api)
        session = validate_success(api.get_session(ctx["session"]["id"], FRONTDESK), 200)
        assert session["seats_taken"] == 0, session["seats_taken"]

    def test_seats_available_restored(self, api):
        """PRD §2.5: "For any session, `seats_taken` plus `seats_available` always
        equals `capacity`; every seat released exactly offsets a seat taken."

        Design: Difficulty/compensating_invariant/session_seats_conserved_on_flight_cancel
        """
        ctx = self._setup(api)
        session = validate_success(api.get_session(ctx["session"]["id"], FRONTDESK), 200)
        assert session["seats_available"] == 4, session["seats_available"]
