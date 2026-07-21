"""Departure-cancel refund cascade, seat-ledger conservation, and departure-full gating
(queue-A rules 4/9 + corner)."""
from test_helpers import (
    validate_success, validate_error, OPERATOR,
    ApiErrorId,
    assert_departure_seat_identity,
    setup_paid_in_full_enrollment, setup_open_departure, enroll, set_clock,
)


class TestDepartureCancelCascade:
    """Design: Difficulty/transitive_cascade/departure_cancel_cascades_enrollment_plan_refund_depth3"""

    def _cancelled_departure(self, api):
        ctx = setup_paid_in_full_enrollment(api, clock="2026-08-18T00:00:00Z", price_cents=250000)
        validate_success(api.cancel_departure(ctx["departure"]["id"], OPERATOR, {"reason": "supplier_failure"}))
        return ctx

    def test_enrollment_cancelled_with_departure_reason_and_refunded(self, api):
        """PRD §3.2: "each enrollment on the departure whose lifecycle_status is not already
        CANCELLED transitions to CANCELLED with cancel_reason set to DEPARTURE_CANCELLED;
        each such cancellation drives that enrollment's active or paid plan to REFUND_DUE;
        each plan set to REFUND_DUE then appends a refund payment for the full amount
        received (operator cancellation forces the refund percentage to 1.00 with no penalty
        retained) and settles to REFUNDED, moving the enrollment's payment_status to
        REFUNDED."

        Design: Difficulty/transitive_cascade/departure_cancel_cascades_enrollment_plan_refund_depth3
        """
        ctx = self._cancelled_departure(api)
        enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], OPERATOR))
        assert enr["lifecycle_status"] == "CANCELLED"
        assert enr["cancel_reason"] == "DEPARTURE_CANCELLED"
        assert enr["payment_status"] == "REFUNDED"

    def test_plan_fully_refunded_and_seat_released(self, api):
        """PRD §3.2: "each plan set to REFUND_DUE then appends a refund payment for the full
        amount received (operator cancellation forces the refund percentage to 1.00 with no
        penalty retained) and settles to REFUNDED".
        PRD §3.2: "After the cascade the departure recomputes free_spots_earned,
        available_seats, and the leader's free_spot_credit_cents."

        Design: Difficulty/transitive_cascade/departure_cancel_cascades_enrollment_plan_refund_depth3
        """
        ctx = self._cancelled_departure(api)
        plan = validate_success(api.get_payment_plan(ctx["plan"]["id"], OPERATOR))
        dep = validate_success(api.get_departure(ctx["departure"]["id"], OPERATOR))
        assert plan["status"] == "REFUNDED"
        assert plan["amount_refunded_cents"] == 250000
        assert dep["available_seats"] == 30  # capacity restored after the only enrollment is cancelled


class TestCancellationConservesSeats:
    """Design: Difficulty/compensating_invariant/cancellation_conserves_seats_capacity_identity_holds"""

    def test_seat_identity_before_cancellation(self, api):
        """PRD §3.8: "available_seats is the capacity minus active_enrollment_count minus
        free_spots_earned; and by construction the capacity always equals the sum of the
        active enrollments, the earned free spots, and the available seats."

        Design: Difficulty/compensating_invariant/cancellation_conserves_seats_capacity_identity_holds
        """
        ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", capacity=30)
        enroll(api, ctx["departure"]["id"], traveler_name="Ola Tu", traveler_gender="FEMALE")
        dep = validate_success(api.get_departure(ctx["departure"]["id"], OPERATOR))
        assert dep["available_seats"] == 29
        assert dep["active_enrollment_count"] == 1
        assert dep["free_spots_earned"] == 0
        assert_departure_seat_identity(dep)

    def test_seat_identity_after_cancellation(self, api):
        """PRD §3.6: "moves the enrollment's payment_status to REFUNDED, and recomputes the
        departure's active_enrollment_count, free_spots_earned, and available_seats plus the
        leader's free_spot_credit_cents."
        PRD §3.8: "by construction the capacity always equals the sum of the active
        enrollments, the earned free spots, and the available seats."

        Design: Difficulty/compensating_invariant/cancellation_conserves_seats_capacity_identity_holds
        """
        ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", capacity=30)
        enr = enroll(api, ctx["departure"]["id"], traveler_name="Ola Tu", traveler_gender="FEMALE")
        validate_success(api.cancel_enrollment(enr["id"], OPERATOR, {"reason": "traveler"}))
        dep = validate_success(api.get_departure(ctx["departure"]["id"], OPERATOR))
        assert dep["available_seats"] == 30
        assert dep["active_enrollment_count"] == 0
        assert dep["free_spots_earned"] == 0
        assert_departure_seat_identity(dep)


def test_enrollment_when_no_seats_returns_departure_full(api):
    """PRD §3.3: "it is refused with ERR_DEPARTURE_FULL when the departure's available_seats
    is below 1."

    Design: Corner/validations/enrollment_when_no_seats_returns_departure_full
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", capacity=1, min_to_guarantee=1)
    enroll(api, ctx["departure"]["id"], traveler_name="Seat One")  # available_seats now 0
    resp = api.create_enrollment(
        {"departure_id": ctx["departure"]["id"], "traveler_name": "Seat Two",
         "traveler_dob": "2010-05-02T00:00:00Z", "traveler_gender": "MALE"}, OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_DEPARTURE_FULL.value, expected_status=409)


def test_enrollment_after_deadline_returns_enrollment_closed(api):
    """PRD §3.3: "The enrollment is refused with ERR_ENROLLMENT_CLOSED when the logical
    clock is later than the departure's enrollment_deadline".

    Design: Corner/validations/enrollment_after_deadline_returns_enrollment_closed
    """
    ctx = setup_open_departure(api, clock="2026-07-15T00:00:00Z")  # enrollment_deadline 2026-09-01
    set_clock(api, "2026-09-02T00:00:00Z")  # now past the deadline
    resp = api.create_enrollment(
        {"departure_id": ctx["departure"]["id"], "traveler_name": "Late L",
         "traveler_dob": "2010-05-01T00:00:00Z", "traveler_gender": "MALE"}, OPERATOR,
    )
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_CLOSED.value, expected_status=422)
