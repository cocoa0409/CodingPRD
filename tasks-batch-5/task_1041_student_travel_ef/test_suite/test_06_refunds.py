"""Refund quoting (dual variant + tier boundary), payment-state precedence, and money
conservation on cancellation (queue-A rules 1/5/6/9 + corner)."""
import pytest
from test_helpers import (
    validate_success, validate_error, OPERATOR,
    ApiErrorId,
    setup_enrollment_with_deposit, setup_paid_in_full_enrollment, setup_open_departure,
    enroll, make_plan, list_plan_payments, find_payment_by_kind,
)


class TestRefundQuoteDualVariant:
    """Design: Difficulty/dual_variant_calc/refund_provisional_over_price_locked_vs_final_over_amount_paid"""

    def _partial_enrollment(self, api):
        # clock 2026-08-18 -> 75 days before depart 2026-11-01 -> tier 0.75; deposit 30000 only.
        return setup_enrollment_with_deposit(
            api, clock="2026-08-18T00:00:00Z", deposit_cents=30000,
            dep_overrides={"price_per_traveler_cents": 250000},
        )

    def test_provisional_over_locked_price_and_tier(self, api):
        """PRD §3.6: "The what-if preview reports, at the current clock, both variants of
        the refund: a provisional_refund_cents computed over the full locked price as though
        the plan will ultimately be paid in full, and a final_refund_cents computed over the
        actual amount_paid_cents; the two diverge whenever the amount paid differs from the
        locked price. The preview also returns the selected refund_pct and the days_before
        figure that chose the tier, and it changes no state."
        PRD §3.6: "0.75 when there are at least 60 but fewer than 90".

        Design: Difficulty/dual_variant_calc/refund_provisional_over_price_locked_vs_final_over_amount_paid
        """
        ctx = self._partial_enrollment(api)
        q = validate_success(api.get_refund_quote(ctx["enrollment"]["id"], OPERATOR))
        assert q["days_before"] == 75
        assert q["refund_pct"] == pytest.approx(0.75)
        assert q["provisional_refund_cents"] == 187500  # round(250000 * 0.75)

    def test_final_over_amount_paid_diverges_from_provisional(self, api):
        """PRD §3.6: "a provisional_refund_cents computed over the full locked price as
        though the plan will ultimately be paid in full, and a final_refund_cents computed
        over the actual amount_paid_cents; the two diverge whenever the amount paid differs
        from the locked price."

        Design: Difficulty/dual_variant_calc/refund_provisional_over_price_locked_vs_final_over_amount_paid
        """
        ctx = self._partial_enrollment(api)
        q = validate_success(api.get_refund_quote(ctx["enrollment"]["id"], OPERATOR))
        assert q["final_refund_cents"] == 22500  # round(30000 * 0.75)
        assert q["provisional_refund_cents"] != q["final_refund_cents"]


class TestRefundTierTimeBoundary:
    """Design: Difficulty/boundary_precision_check/refund_tier_time_boundary_at_exactly_90_days"""

    def test_at_exactly_90_days_before_pct_is_full(self, api):
        """PRD §3.6: "The refund percentage is 1.00 when there are at least 90 whole days
        before departure; 0.75 when there are at least 60 but fewer than 90".
        PRD §3.6: "Let the number of whole days before departure be the difference between
        the departure's depart_date and the current logical clock, divided by one day and
        taken as the floor."

        Design: Difficulty/boundary_precision_check/refund_tier_time_boundary_at_exactly_90_days
        """
        # clock 2026-08-03 is exactly 90 days before depart 2026-11-01.
        ctx = setup_paid_in_full_enrollment(api, clock="2026-08-03T00:00:00Z", price_cents=250000)
        q = validate_success(api.get_refund_quote(ctx["enrollment"]["id"], OPERATOR))
        assert q["days_before"] == 90
        assert q["refund_pct"] == pytest.approx(1.00)
        assert q["final_refund_cents"] == 250000

    def test_one_day_inside_ninety_drops_to_075(self, api):
        """PRD §3.6: "The refund percentage is 1.00 when there are at least 90 whole days
        before departure; 0.75 when there are at least 60 but fewer than 90".

        Design: Difficulty/boundary_precision_check/refund_tier_time_boundary_at_exactly_90_days
        """
        # clock 2026-08-04 is 89 days before depart 2026-11-01 -> just inside the 0.75 tier.
        ctx = setup_paid_in_full_enrollment(api, clock="2026-08-04T00:00:00Z", price_cents=250000)
        q = validate_success(api.get_refund_quote(ctx["enrollment"]["id"], OPERATOR))
        assert q["days_before"] == 89
        assert q["refund_pct"] == pytest.approx(0.75)
        assert q["final_refund_cents"] == 187500  # round(250000 * 0.75)


class TestPaymentStateBeatsFiscal:
    """Design: Difficulty/priority_pair_validation_conflict/payment_state_beats_fiscal_on_refunded_plan"""

    def _refunded_plan_ctx(self, api):
        ctx = setup_enrollment_with_deposit(api, clock="2026-08-18T00:00:00Z", deposit_cents=30000)
        validate_success(api.cancel_enrollment(ctx["enrollment"]["id"], OPERATOR, {"reason": "traveler"}))
        return ctx  # plan is now REFUNDED

    def test_payment_to_refunded_plan_over_balance_returns_invalid_state(self, api):
        """PRD §3.5: "Recording a payment is allowed only against an active plan. If the
        target plan is not ACTIVE — that is, it is PAID, REFUND_DUE, REFUNDED, or SUPERSEDED
        — the payment is rejected with ERR_INVALID_STATE."
        PRD §2.9: "State legality is next ... Business rules — temporal windows, capacity,
        fiscal limits, and concurrency — are evaluated after those foundations".

        Design: Difficulty/priority_pair_validation_conflict/payment_state_beats_fiscal_on_refunded_plan
        """
        ctx = self._refunded_plan_ctx(api)
        resp = api.create_payment(
            {"payment_plan_id": ctx["plan"]["id"], "amount_cents": 9999999, "kind": "INSTALLMENT"}, OPERATOR
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)

    def test_state_error_preempts_the_overpayment_error(self, api):
        """PRD §2.9: "State legality is next ... Business rules — temporal windows, capacity,
        fiscal limits, and concurrency — are evaluated after those foundations".
        PRD §3.5: "If the target plan is not ACTIVE ... the payment is rejected with
        ERR_INVALID_STATE."

        Design: Difficulty/priority_pair_validation_conflict/payment_state_beats_fiscal_on_refunded_plan
        """
        ctx = self._refunded_plan_ctx(api)
        resp = api.create_payment(
            {"payment_plan_id": ctx["plan"]["id"], "amount_cents": 9999999, "kind": "INSTALLMENT"}, OPERATOR
        )
        body = resp.json()["data"]
        assert body["error_id"] == ApiErrorId.ERR_INVALID_STATE.value
        assert body["error_id"] != ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value


class TestCancellationConservesMoney:
    """Design: Difficulty/compensating_invariant/cancellation_conserves_money_refund_plus_penalty_equals_paid"""

    def _cancelled_ctx(self, api):
        ctx = setup_enrollment_with_deposit(api, clock="2026-08-18T00:00:00Z", deposit_cents=30000)
        validate_success(api.cancel_enrollment(ctx["enrollment"]["id"], OPERATOR, {"reason": "traveler"}))
        return ctx

    def test_refund_and_penalty_ledger_rows_written(self, api):
        """PRD §3.6: "computes the refund using the final refund rule, appends one refund
        payment and one penalty-retained payment, settles the plan to REFUNDED".
        PRD §3.6: "The penalty retained is the amount actually paid minus the smaller of the
        computed refund and the amount paid".

        Design: Difficulty/compensating_invariant/cancellation_conserves_money_refund_plus_penalty_equals_paid
        """
        ctx = self._cancelled_ctx(api)
        payments = list_plan_payments(api, ctx["plan"]["id"])
        refunds = find_payment_by_kind(payments, "REFUND")
        penalties = find_payment_by_kind(payments, "PENALTY_RETAINED")
        assert any(p["amount_cents"] == 22500 for p in refunds), "expected a REFUND of 22500"
        assert any(p["amount_cents"] == 7500 for p in penalties), "expected a PENALTY_RETAINED of 7500"

    def test_refund_plus_penalty_equals_amount_paid(self, api):
        """PRD §3.6: "so that the amount paid always equals the retained penalty plus the
        refund actually issued (the refund actually issued being capped at the amount paid)."

        Design: Difficulty/compensating_invariant/cancellation_conserves_money_refund_plus_penalty_equals_paid
        """
        ctx = self._cancelled_ctx(api)
        plan = validate_success(api.get_payment_plan(ctx["plan"]["id"], OPERATOR))
        assert plan["amount_refunded_cents"] == 22500
        assert 22500 + 7500 == 30000  # refund + penalty == amount paid before cancel


def test_payment_over_balance_returns_payment_exceeds_balance(api):
    """PRD §3.5: "A payment may not overpay: its amount_cents may not exceed the remaining
    balance, which is total_cents minus the current amount_paid_cents; an attempt to exceed
    it is rejected with ERR_PAYMENT_EXCEEDS_BALANCE."

    Design: Corner/validations/payment_over_balance_returns_payment_exceeds_balance
    """
    ctx = setup_open_departure(api, clock="2026-08-18T00:00:00Z", price_per_traveler_cents=250000)
    enr = enroll(api, ctx["departure"]["id"], traveler_name="Over O")
    plan = make_plan(api, enr["id"], enr["version"], installment_count=1)  # total 250000, nothing paid
    resp = api.create_payment({"payment_plan_id": plan["id"], "amount_cents": 260000, "kind": "DEPOSIT"}, OPERATOR)
    validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE.value, expected_status=422)
