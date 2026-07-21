"""Enrollment lifecycle: parallel axes, confirm gating, cancel idempotency, rebook target."""
from test_helpers import (
    validate_success, validate_error, OPERATOR,
    ApiErrorId,
    setup_enrollment_with_deposit, setup_confirmed_enrollment, make_departure,
)


class TestParallelAxes:
    """Design: Difficulty/non_linear_state_machine/enrollment_parallel_axes_lifecycle_and_payment_independent"""

    def test_confirm_moves_lifecycle_but_not_payment_axis(self, api):
        """PRD §3.3: "Confirming an enrollment advances its lifecycle from PENDING to
        CONFIRMED."
        PRD §3.5: "An enrollment's payment_status moves along its own axis, independent of
        the lifecycle axis, as money arrives."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_axes_lifecycle_and_payment_independent
        """
        ctx = setup_enrollment_with_deposit(api, clock="2026-08-18T00:00:00Z", deposit_cents=30000,
                                            dep_overrides={"price_per_traveler_cents": 250000})
        confirmed = validate_success(api.confirm_enrollment(ctx["enrollment"]["id"], OPERATOR))
        assert confirmed["lifecycle_status"] == "CONFIRMED"
        assert confirmed["payment_status"] == "PARTIAL", "payment axis must be untouched by the lifecycle transition"

    def test_balance_payment_moves_payment_but_not_lifecycle_axis(self, api):
        """PRD §3.5: "A payment that brings the paid total to at least total_cents moves it
        to PAID_IN_FULL — either PARTIAL → PAID_IN_FULL when partial payments preceded it,
        or UNPAID → PAID_IN_FULL when a single payment settles the whole balance."
        PRD §3.5: "An enrollment's payment_status moves along its own axis, independent of
        the lifecycle axis, as money arrives."

        Design: Difficulty/non_linear_state_machine/enrollment_parallel_axes_lifecycle_and_payment_independent
        """
        ctx = setup_enrollment_with_deposit(api, clock="2026-08-18T00:00:00Z", deposit_cents=30000,
                                            dep_overrides={"price_per_traveler_cents": 250000})
        validate_success(api.confirm_enrollment(ctx["enrollment"]["id"], OPERATOR))
        # remaining 220000 pays the plan in full
        validate_success(
            api.create_payment({"payment_plan_id": ctx["plan"]["id"], "amount_cents": 220000, "kind": "INSTALLMENT"}, OPERATOR),
            expected_status=201,
        )
        enr = validate_success(api.get_enrollment(ctx["enrollment"]["id"], OPERATOR))
        assert enr["payment_status"] == "PAID_IN_FULL"
        assert enr["lifecycle_status"] == "CONFIRMED", "lifecycle axis must be untouched by the payment transition"


# NOTE: TestConfirmRequiresOpenDeparture (test_confirm_on_draft_departure_rejected,
# test_enrollment_stays_pending_after_rejected_confirm) was DELETED — unique-derivability gap.
# Both tests required a PENDING enrollment sitting on a non-OPEN/GUARANTEED departure, built by
# enrolling on a DRAFT departure. PRD §3.2 uniquely derives DRAFT available_seats = 0 ("A new
# departure starts in DRAFT ... every derived counter at 0"; publishing "initializes
# available_seats to capacity"), so §3.3's gate refuses any DRAFT enrollment with
# ERR_DEPARTURE_FULL. No PRD-faithful path yields a PENDING enrollment on a non-open departure
# (CANCELLED cascades the enrollment to CANCELLED → ambiguous ERR_INVALID_STATE vs
# ERR_DEPARTURE_NOT_OPEN). Scaffold rule:
# Difficulty/cross_entity_state_dependency/enrollment_confirm_requires_departure_open_or_guaranteed.


def test_cancel_already_cancelled_enrollment_returns_invalid_state(api):
    """PRD §3.6: "an attempt to cancel an enrollment that is in any other lifecycle state
    is rejected with ERR_INVALID_STATE."

    Design: Corner/state_machines/cancel_already_cancelled_enrollment_returns_invalid_state
    """
    ctx = setup_enrollment_with_deposit(api, clock="2026-08-18T00:00:00Z", deposit_cents=30000)
    validate_success(api.cancel_enrollment(ctx["enrollment"]["id"], OPERATOR, {"reason": "traveler"}))
    resp = api.cancel_enrollment(ctx["enrollment"]["id"], OPERATOR, {"reason": "traveler"})
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_rebook_to_draft_departure_returns_rebook_target_invalid(api):
    """PRD §3.6: "The owning group leader (or an operator) supplies target_departure_id,
    which must reference a departure whose status is OPEN or GUARANTEED and whose
    available_seats is at least 1; otherwise the request is rejected with
    ERR_REBOOK_TARGET_INVALID."

    Design: Corner/validations/rebook_to_draft_departure_returns_rebook_target_invalid
    """
    ctx = setup_confirmed_enrollment(api, clock="2026-08-18T00:00:00Z", deposit_cents=30000)
    # Second departure left DRAFT (never opened).
    draft_target = make_departure(
        api, ctx["tour"]["id"], ctx["group_leader"]["id"],
        depart_date="2026-12-01T00:00:00Z", return_date="2026-12-08T00:00:00Z",
        enrollment_deadline="2026-10-01T00:00:00Z", early_bird_cutoff="2026-09-01T00:00:00Z",
    )
    resp = api.rebook_enrollment(ctx["enrollment"]["id"], {"target_departure_id": draft_target["id"]}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_REBOOK_TARGET_INVALID.value, expected_status=409)
