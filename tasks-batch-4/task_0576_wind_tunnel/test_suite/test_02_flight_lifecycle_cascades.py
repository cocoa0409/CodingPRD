"""Reflight credit variants and abort/close cascades (PRD §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    abort_flight_payload,
    make_instructor_headers,
    setup_aborted_flight,
    setup_checked_in_flight,
    setup_exhausted_booking_checked_in,
    validate_success,
)

FRONTDESK = TEST_USERS["frontdesk_headers"]


class TestReflightCreditVariants:
    """Provisional grant at abort vs final reconciliation at close."""

    def test_provisional_grant_at_abort(self, api):
        """PRD §3.7: "At the moment of **abort**, the credit is granted
        **provisionally** at the full slot: the flight's `reflight_credit_granted` is
        set to its `scheduled_minutes`, the member's `reflight_credit_minutes`
        increases by that same `scheduled_minutes`, and `total_credits_minted`
        increases by it as well."

        Design: Difficulty/dual_variant_calc/reflight_credit_provisional_vs_final
        """
        ctx = setup_checked_in_flight(api, booking_kw={"party_size": 1}, scheduled_minutes=2)
        instr = make_instructor_headers(ctx["instructor"]["id"])
        aborted = validate_success(
            api.abort_flight(ctx["flight"]["id"], abort_flight_payload(1), instr), 200
        )
        assert aborted["reflight_credit_granted"] == 2, aborted["reflight_credit_granted"]

    def test_final_reconciliation_at_close(self, api):
        """PRD §3.7: "At **session close**, each aborted flight's credit is reconciled
        to its **final** value: the credit that should stand is the flight's
        `scheduled_minutes` less the `flown_minutes` recorded at abort — that is, only
        the unflown remainder."

        Design: Difficulty/dual_variant_calc/reflight_credit_provisional_vs_final
        """
        ctx = setup_aborted_flight(api, flown_minutes=1, booking_kw={"party_size": 1}, scheduled_minutes=2)
        validate_success(api.close_session(ctx["session"]["id"], FRONTDESK), 200)
        flight = validate_success(api.get_flight(ctx["flight"]["id"], FRONTDESK), 200)
        assert flight["reflight_credit_granted"] == 1, flight["reflight_credit_granted"]
        member = validate_success(api.get_member(ctx["member"]["id"], FRONTDESK), 200)
        assert member["reflight_credit_minutes"] == 1, member["reflight_credit_minutes"]


class TestAbortBranchDivergentEffects:
    """From CHECKED_IN the ABORTED branch refunds minutes AND grants credit."""

    def test_abort_status_and_credit(self, api):
        """PRD §3.6: "Abort also records the supplied `flown_minutes` on the flight and
        sets its `minutes_charged` to 0, and grants a provisional reflight credit as
        described in Section 3.7."
        PRD §3.7: "the flight's `reflight_credit_granted` is set to its
        `scheduled_minutes`".

        Design: Difficulty/non_linear_state_machine/flight_branching_abort_divergent_side_effects
        """
        ctx = setup_checked_in_flight(api, booking_kw={"party_size": 1}, scheduled_minutes=2)
        instr = make_instructor_headers(ctx["instructor"]["id"])
        aborted = validate_success(
            api.abort_flight(ctx["flight"]["id"], abort_flight_payload(1), instr), 200
        )
        assert aborted["status"] == "ABORTED", aborted["status"]
        assert aborted["reflight_credit_granted"] == 2, aborted["reflight_credit_granted"]

    def test_abort_refunds_minutes(self, api):
        """PRD §3.6: "Abort triggers a three-hop cascade: the flight's
        `scheduled_minutes` are refunded to the booking, so `minutes_remaining`
        increases by that amount".

        Design: Difficulty/non_linear_state_machine/flight_branching_abort_divergent_side_effects
        """
        ctx = setup_checked_in_flight(api, booking_kw={"party_size": 1}, scheduled_minutes=2)
        instr = make_instructor_headers(ctx["instructor"]["id"])
        api.abort_flight(ctx["flight"]["id"], abort_flight_payload(1), instr)
        booking = validate_success(api.get_booking(ctx["booking"]["id"], FRONTDESK), 200)
        assert booking["minutes_remaining"] == 2, booking["minutes_remaining"]


class TestAbortCascadeDepth3:
    """Flight.abort -> booking.minutes -> booking.status -> member counter."""

    def test_abort_refund_flips_booking_confirmed(self, api):
        """PRD §3.6: "the flight's `scheduled_minutes` are refunded to the booking, so
        `minutes_remaining` increases by that amount; if the booking had been
        `EXHAUSTED` this refund flips it `EXHAUSTED → CONFIRMED`; and that flip
        increments the member's `confirmed_booking_count` by one."

        Design: Difficulty/transitive_cascade/abort_cascade_flight_booking_member_depth3
        """
        ctx = setup_exhausted_booking_checked_in(api)
        instr = make_instructor_headers(ctx["instructor"]["id"])
        api.abort_flight(ctx["flight"]["id"], abort_flight_payload(0), instr)
        booking = validate_success(api.get_booking(ctx["booking"]["id"], FRONTDESK), 200)
        assert booking["minutes_remaining"] == 2, booking["minutes_remaining"]
        assert booking["status"] == "CONFIRMED", booking["status"]

    def test_abort_increments_member_confirmed_count(self, api):
        """PRD §3.6: "if the booking had been `EXHAUSTED` this refund flips it
        `EXHAUSTED → CONFIRMED`; and that flip increments the member's
        `confirmed_booking_count` by one."

        Design: Difficulty/transitive_cascade/abort_cascade_flight_booking_member_depth3
        """
        ctx = setup_exhausted_booking_checked_in(api)
        instr = make_instructor_headers(ctx["instructor"]["id"])
        api.abort_flight(ctx["flight"]["id"], abort_flight_payload(0), instr)
        member = validate_success(api.get_member(ctx["member"]["id"], FRONTDESK), 200)
        assert member["confirmed_booking_count"] == 1, member["confirmed_booking_count"]


class TestCloseCascadeDepth2:
    """Session.close -> flight credit reconciled -> member credit adjusted."""

    def test_close_reconciles_flight_credit(self, api):
        """PRD §3.6: "Every `ABORTED` flight has its reflight credit reconciled from
        provisional to final (Section 3.7)."
        PRD §3.7: "the credit that should stand is the flight's `scheduled_minutes`
        less the `flown_minutes` recorded at abort — that is, only the unflown
        remainder."

        Design: Difficulty/transitive_cascade/close_cascade_session_flight_member_depth2
        """
        ctx = setup_aborted_flight(api, flown_minutes=1, booking_kw={"party_size": 1}, scheduled_minutes=2)
        api.close_session(ctx["session"]["id"], FRONTDESK)
        flight = validate_success(api.get_flight(ctx["flight"]["id"], FRONTDESK), 200)
        assert flight["reflight_credit_granted"] == 1, flight["reflight_credit_granted"]

    def test_close_reconciles_member_credit(self, api):
        """PRD §3.7: "The reconciliation computes the delta between the final value and
        the provisional value already granted, a quantity that is zero or negative,
        and applies that delta to both the member's `reflight_credit_minutes` and
        `total_credits_minted`, and writes the final value into the flight's
        `reflight_credit_granted`."

        Design: Difficulty/transitive_cascade/close_cascade_session_flight_member_depth2
        """
        ctx = setup_aborted_flight(api, flown_minutes=1, booking_kw={"party_size": 1}, scheduled_minutes=2)
        session = validate_success(api.close_session(ctx["session"]["id"], FRONTDESK), 200)
        assert session["op_status"] == "CLOSED", session["op_status"]
        member = validate_success(api.get_member(ctx["member"]["id"], FRONTDESK), 200)
        assert member["reflight_credit_minutes"] == 1, member["reflight_credit_minutes"]
