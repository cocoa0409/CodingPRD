"""Restitution payments: waterfall allocation, exact-equality PAID_IN_FULL
boundary, return (NSF) cascade and the conserved outstanding equation."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_demand_outstanding_invariant,
    get_case,
    make_analyst_headers,
    make_manager_headers,
    make_store,
    post_payment,
    record_and_post_payment,
    record_payment,
    return_payment,
    setup_case_with_issued_demand,
    validate_error,
    validate_success,
)
from test_helpers.constants import ADMIN_1, ANALYST_1, MANAGER_1


def _get_demand(api, demand_id):
    return validate_success(
        api.get_civil_demand(demand_id, make_manager_headers(MANAGER_1))
    )


def _get_store(api, store_id):
    return validate_success(api.get_store(store_id, make_manager_headers(MANAGER_1)))


class TestPaymentStateMachine:
    def test_payment_return_from_received_returns_invalid_state(self, api):
        """PRD §3.6: "A payment later dishonored — the NSF path — is returned:
        only a `POSTED` payment can be returned, and returning it adds a
        2500-cent fee to the demand's `fees_incurred_cents`, subtracts the
        payment's amount from `paid_to_date_cents`, subtracts that payment's
        bucket allocations back out of each paid counter, and recomputes
        `outstanding_cents`."

        A merely-RECEIVED payment cannot be returned; no NSF fee accrues.

        Design: Corner/state_machines/payment_return_from_received_returns_invalid_state
        """
        store = make_store(store_number="S042", name="Store 42")
        ctx = setup_case_with_issued_demand(store["id"], manual_loss_cents=30000)
        payment = record_payment(ctx["demand"]["id"], 5000)
        resp = api.return_restitution_payment(
            payment["id"], make_analyst_headers(ANALYST_1)
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)
        demand = _get_demand(api, ctx["demand"]["id"])
        assert demand["fees_incurred_cents"] == 0
        assert demand["outstanding_cents"] == 30000


class TestWaterfallAllocation:
    def test_waterfall_partial_payment_penalty_before_merch(self, api):
        """PRD §3.6: "Posting allocates the amount across three buckets in a
        fixed waterfall order: first toward unpaid NSF fees, then toward the
        unpaid statutory penalty, then toward the unpaid
        merchandise-loss-plus-recovery-cost bucket, each bucket receiving the
        lesser of the remaining payment and that bucket's unpaid balance. The
        allocations land in the payment's `applied_fees_cents`,
        `applied_penalty_cents`, and `applied_merch_cents`."

        A 15000 payment against due 40000 (penalty 10000 + merch 30000) fills
        the penalty bucket first.

        Design: Corner/calculations/waterfall_partial_payment_penalty_before_merch
        """
        store = make_store(store_number="S055", name="Store 55")
        ctx = setup_case_with_issued_demand(
            store["id"], manual_loss_cents=30000, basis="STATUTORY",
            priors_offense_count=0,
        )
        payment = record_payment(ctx["demand"]["id"], 15000, method="MONEY_ORDER")
        posted = post_payment(payment["id"])
        assert posted["applied_fees_cents"] == 0
        assert posted["applied_penalty_cents"] == 10000, "penalty bucket first"
        assert posted["applied_merch_cents"] == 5000
        demand = _get_demand(api, ctx["demand"]["id"])
        assert demand["outstanding_cents"] == 25000
        assert demand["status"] == "PARTIALLY_PAID"
        assert_demand_outstanding_invariant(demand)

    def test_immediate_visibility_post_then_read(self, api):
        """PRD §2.10: "Consistency is immediate: every operation applies its
        full cascade before responding."
        PRD §3.6: "Posting allocates the amount across three buckets in a fixed
        waterfall order: first toward unpaid NSF fees, then toward the unpaid
        statutory penalty, then toward the unpaid
        merchandise-loss-plus-recovery-cost bucket, each bucket receiving the
        lesser of the remaining payment and that bucket's unpaid balance."

        The post response itself carries the allocation, and the very next
        demand read reflects the recomputed rollups.

        Design: Corner/consistency_model/immediate_visibility_post_payment_then_read
        """
        store = make_store(store_number="S500", name="Store 500")
        ctx = setup_case_with_issued_demand(
            store["id"], manual_loss_cents=30000, basis="STATUTORY",
            priors_offense_count=0,
        )
        payment = record_payment(ctx["demand"]["id"], 10000)
        posted = post_payment(payment["id"])
        assert posted["applied_penalty_cents"] == 10000
        assert posted["applied_merch_cents"] == 0
        demand = _get_demand(api, ctx["demand"]["id"])
        assert demand["outstanding_cents"] == 30000
        assert demand["paid_to_date_cents"] == 10000
        assert demand["status"] == "PARTIALLY_PAID"


class TestExactOutstandingBoundary:
    def _setup_two_demands(self, api):
        """Two cases, loss 30000 each; STATUTORY demands due 40000 each."""
        store = make_store(store_number="S201", name="Store 201")
        ctx_a = setup_case_with_issued_demand(
            store["id"], manual_loss_cents=30000, basis="STATUTORY",
            priors_offense_count=0,
        )
        ctx_b = setup_case_with_issued_demand(
            store["id"], manual_loss_cents=30000, basis="STATUTORY",
            priors_offense_count=0, scheduled_start="2026-08-02T11:00:00Z",
            scheduled_end="2026-08-02T12:00:00Z",
        )
        return store, ctx_a, ctx_b

    def test_payment_exact_outstanding_flips_paid_in_full(self, api):
        """PRD §3.6: "The demand's status follows the balance: a posting that
        leaves paid-to-date strictly between zero and the full due-plus-fees
        total flips `ISSUED` to `PARTIALLY_PAID`, and a posting that drives
        `outstanding_cents` to exactly zero flips the demand to `PAID_IN_FULL`
        — including a first payment that covers the full amount in one shot,
        moving straight from `ISSUED`."

        Design: Difficulty/boundary_precision_check/payment_exact_outstanding_vs_one_cent_short
        """
        _store, ctx_a, _ctx_b = self._setup_two_demands(api)
        posted = record_and_post_payment(ctx_a["demand"]["id"], 40000, method="CARD")
        assert posted["applied_penalty_cents"] == 10000, "penalty bucket before merch"
        assert posted["applied_merch_cents"] == 30000
        demand = _get_demand(api, ctx_a["demand"]["id"])
        assert demand["outstanding_cents"] == 0
        assert demand["paid_to_date_cents"] == 40000
        assert demand["status"] == "PAID_IN_FULL", "exact-equality boundary"
        assert_demand_outstanding_invariant(demand)

    def test_payment_one_cent_short_stays_partially_paid(self, api):
        """PRD §3.6: "The demand's status follows the balance: a posting that
        leaves paid-to-date strictly between zero and the full due-plus-fees
        total flips `ISSUED` to `PARTIALLY_PAID`, and a posting that drives
        `outstanding_cents` to exactly zero flips the demand to `PAID_IN_FULL`
        — including a first payment that covers the full amount in one shot,
        moving straight from `ISSUED`."

        39999 against outstanding 40000 leaves outstanding_cents == 1.

        Design: Difficulty/boundary_precision_check/payment_exact_outstanding_vs_one_cent_short
        """
        _store, _ctx_a, ctx_b = self._setup_two_demands(api)
        record_and_post_payment(ctx_b["demand"]["id"], 39999, method="CARD")
        demand = _get_demand(api, ctx_b["demand"]["id"])
        assert demand["outstanding_cents"] == 1, "one cent short"
        assert demand["status"] == "PARTIALLY_PAID"
        assert_demand_outstanding_invariant(demand)

    def test_payment_exceeding_outstanding_rejected_exact_boundary(self, api):
        """PRD §3.6: "Posting is the committing step: the payment must be
        `RECEIVED`, its demand must be `ISSUED` or `PARTIALLY_PAID`
        (`ERR_DEMAND_NOT_PAYABLE` otherwise), and `amount_cents` must not
        exceed the demand's `outstanding_cents`
        (`ERR_PAYMENT_EXCEEDS_OUTSTANDING` — overpayment is impossible by
        construction)."

        40001 against outstanding 40000 fails; exactly 40000 posts.

        Design: Corner/errors/payment_exceeding_outstanding_rejected_exact_boundary
        """
        store = make_store(store_number="S087", name="Store 87")
        ctx = setup_case_with_issued_demand(
            store["id"], manual_loss_cents=30000, basis="STATUTORY",
            priors_offense_count=0,
        )
        pay_over = record_payment(ctx["demand"]["id"], 40001)
        resp = api.post_restitution_payment(
            pay_over["id"], make_analyst_headers(ANALYST_1)
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING)
        after = validate_success(
            api.get_restitution_payment(pay_over["id"], make_analyst_headers(ANALYST_1))
        )
        assert after["status"] == "RECEIVED", "rejected payment is not posted"
        pay_ok = record_and_post_payment(ctx["demand"]["id"], 40000)
        assert pay_ok["status"] == "POSTED"
        assert _get_demand(api, ctx["demand"]["id"])["status"] == "PAID_IN_FULL"


class TestStateBeatsFiscal:
    """Written-off demand: posting violates the state gate (step 6) and, for
    an over-amount, the fiscal rule (step 12); the state error must surface."""

    def _setup_written_off(self, api):
        store = make_store(store_number="S180", name="Store 180")
        ctx = setup_case_with_issued_demand(
            store["id"], manual_loss_cents=30000, basis="STATUTORY",
            priors_offense_count=0,
        )
        # amount_due 40000, outstanding 40000 <= cap 50000 -> write-off ok.
        resp = api.write_off_civil_demand(
            ctx["demand"]["id"], make_manager_headers(MANAGER_1)
        )
        validate_success(resp)
        return store, ctx

    def test_payment_on_written_off_demand_reports_state_error(self, api):
        """PRD §2.7: "Every request passes through a single ordered validation
        pipeline, and the first failing check produces the response — later
        checks are not evaluated."
        PRD §2.7: "6. The target entity's own state machine must permit the
        requested transition (`ERR_INVALID_STATE_TRANSITION`, or
        `ERR_DEMAND_NOT_PAYABLE` for a payment posting against a demand that is
        not payable)."
        PRD §2.7: "12. Fiscal rules, always last
        (`ERR_PAYMENT_EXCEEDS_OUTSTANDING`, `ERR_WRITE_OFF_CAP_EXCEEDED`,
        `ERR_RECOVERED_EXCEEDS_LOSS`, `ERR_BASIS_NOT_ALLOWED`)."

        45000 against a WRITTEN_OFF demand with outstanding 40000 violates
        both; the state error (step 6) precedes the fiscal one (step 12).

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_payment_on_written_off_demand
        """
        _store, ctx = self._setup_written_off(api)
        payment = record_payment(ctx["demand"]["id"], 45000)
        resp = api.post_restitution_payment(
            payment["id"], make_analyst_headers(ANALYST_1)
        )
        err = validate_error(resp, ApiErrorId.ERR_DEMAND_NOT_PAYABLE)
        assert err["error_id"] != ApiErrorId.ERR_PAYMENT_EXCEEDS_OUTSTANDING

    def test_payment_on_written_off_demand_leaves_no_partial_mutation(self, api):
        """PRD §3.6: "Posting is the committing step: the payment must be
        `RECEIVED`, its demand must be `ISSUED` or `PARTIALLY_PAID`
        (`ERR_DEMAND_NOT_PAYABLE` otherwise), and `amount_cents` must not
        exceed the demand's `outstanding_cents`
        (`ERR_PAYMENT_EXCEEDS_OUTSTANDING` — overpayment is impossible by
        construction)."

        Even a within-outstanding amount cannot post to a WRITTEN_OFF demand,
        and the rejected post leaves the demand counters untouched.

        Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_payment_on_written_off_demand
        """
        _store, ctx = self._setup_written_off(api)
        payment = record_payment(ctx["demand"]["id"], 1000)
        resp = api.post_restitution_payment(
            payment["id"], make_analyst_headers(ANALYST_1)
        )
        validate_error(resp, ApiErrorId.ERR_DEMAND_NOT_PAYABLE)
        demand = _get_demand(api, ctx["demand"]["id"])
        assert demand["status"] == "WRITTEN_OFF"
        assert demand["paid_to_date_cents"] == 0, "no partial mutation on rejection"


class TestPaymentReturnCascade:
    """Return of an 80000 payment after full settlement: demand counters,
    demand status, case restitution_status, and store rollup all move."""

    def _setup_returned(self, api):
        """Due 130000 (loss 75000; tier2 27500 x 2.0 = 55000 penalty).
        Post 80000 (penalty 55000 + merch 25000), then 50000 (merch).
        Demand PAID_IN_FULL; return the 80000 payment. Returns (store, ctx, pay1)."""
        store = make_store(store_number="S160", name="Store 160")
        ctx = setup_case_with_issued_demand(
            store["id"], manual_loss_cents=75000, basis="STATUTORY",
            priors_offense_count=2,
        )
        assert ctx["demand"]["amount_due_cents"] == 130000
        pay1 = record_and_post_payment(ctx["demand"]["id"], 80000, method="CARD")
        record_and_post_payment(ctx["demand"]["id"], 50000)
        demand = _get_demand(api, ctx["demand"]["id"])
        assert demand["status"] == "PAID_IN_FULL"
        assert _get_store(api, store["id"])["restitution_collected_cents"] == 130000
        return_payment(pay1["id"])
        return store, ctx, pay1

    def test_payment_return_recomputes_demand_counters(self, api):
        """PRD §3.6: "A payment later dishonored — the NSF path — is returned:
        only a `POSTED` payment can be returned, and returning it adds a
        2500-cent fee to the demand's `fees_incurred_cents`, subtracts the
        payment's amount from `paid_to_date_cents`, subtracts that payment's
        bucket allocations back out of each paid counter, and recomputes
        `outstanding_cents`."
        PRD §3.6: "The demand's status unwinds in kind: `PAID_IN_FULL` falls
        back to `PARTIALLY_PAID`, and a `PARTIALLY_PAID` demand whose
        paid-to-date returns to zero falls back to `ISSUED`."

        After the return: fees 2500, paid_to_date 50000, and the invariant
        outstanding == 130000 + 2500 - 50000 = 82500 (the asserted value
        follows the PRD invariant; the design yaml's "107500" miscomputes its
        own annotated formula).

        Design: Difficulty/transitive_cascade/payment_return_cascade_depth4
        """
        _store, ctx, pay1 = self._setup_returned(api)
        payment = validate_success(
            api.get_restitution_payment(pay1["id"], make_analyst_headers(ANALYST_1))
        )
        assert payment["status"] == "RETURNED"
        demand = _get_demand(api, ctx["demand"]["id"])
        assert demand["fees_incurred_cents"] == 2500
        assert demand["paid_to_date_cents"] == 50000, "130000 - 80000"
        assert demand["outstanding_cents"] == 82500, "130000 + 2500 - 50000"
        assert demand["status"] == "PARTIALLY_PAID"
        assert_demand_outstanding_invariant(demand)

    def test_payment_return_recomputes_case_and_store(self, api):
        """PRD §3.6: "The case's `restitution_status` recomputes to
        `OUTSTANDING`, and the store's `restitution_collected_cents` falls by
        the returned amount."
        PRD §3.6: "When a demand reaches `PAID_IN_FULL`, the case's
        `restitution_status` becomes `SETTLED` provided no other issued demand
        on the case still has `outstanding_cents` above zero."

        The return unwinds SETTLED back to OUTSTANDING and the store's
        collected figure from 130000 to 50000.

        Design: Difficulty/transitive_cascade/payment_return_cascade_depth4
        """
        store, ctx, _pay1 = self._setup_returned(api)
        case = get_case(ctx["case"]["id"])
        assert case["restitution_status"] == "OUTSTANDING"
        store_after = _get_store(api, store["id"])
        assert store_after["restitution_collected_cents"] == 50000


class TestOutstandingInvariant:
    """Post 40000 (drives outstanding to 0), then return it: the money
    equation outstanding == amount_due + fees - paid_to_date must hold at
    every step, with no drift on the store rollup."""

    def _setup_posted_full(self, api):
        store = make_store(store_number="S230", name="Store 230")
        ctx = setup_case_with_issued_demand(
            store["id"], manual_loss_cents=30000, basis="STATUTORY",
            priors_offense_count=0,
        )
        assert ctx["demand"]["amount_due_cents"] == 40000
        payment = record_and_post_payment(ctx["demand"]["id"], 40000, method="CARD")
        return store, ctx, payment

    def test_post_then_return_conserves_outstanding_equation(self, api):
        """PRD §3.6: "The demand's `paid_to_date_cents` rises by the posted
        amount and `outstanding_cents` recomputes; after every post and every
        return the invariant holds that `outstanding_cents` equals
        `amount_due_cents` plus `fees_incurred_cents` minus
        `paid_to_date_cents`."

        Forward post drives outstanding to 0; the compensating return restores
        outstanding to exactly 40000 + 2500 - 0 = 42500.

        Design: Difficulty/compensating_invariant/payment_post_return_conserves_outstanding_equation
        """
        _store, ctx, payment = self._setup_posted_full(api)
        demand = _get_demand(api, ctx["demand"]["id"])
        assert demand["outstanding_cents"] == 0
        assert demand["status"] == "PAID_IN_FULL"
        assert_demand_outstanding_invariant(demand)
        return_payment(payment["id"])
        demand = _get_demand(api, ctx["demand"]["id"])
        assert demand["fees_incurred_cents"] == 2500
        assert demand["paid_to_date_cents"] == 0
        assert demand["outstanding_cents"] == 42500, "40000 + 2500 - 0"
        assert_demand_outstanding_invariant(demand)

    def test_return_restores_store_baseline_and_demand_status(self, api):
        """PRD §3.6: "The demand's status unwinds in kind: `PAID_IN_FULL`
        falls back to `PARTIALLY_PAID`, and a `PARTIALLY_PAID` demand whose
        paid-to-date returns to zero falls back to `ISSUED`."
        PRD §3.6: "The case's `restitution_status` recomputes to `OUTSTANDING`,
        and the store's `restitution_collected_cents` falls by the returned
        amount."

        The sole payment's return puts paid_to_date back at zero (demand back
        to ISSUED) and restores the store's collected baseline of 0.

        Design: Difficulty/compensating_invariant/payment_post_return_conserves_outstanding_equation
        """
        store, ctx, payment = self._setup_posted_full(api)
        assert _get_store(api, store["id"])["restitution_collected_cents"] == 40000
        returned = return_payment(payment["id"])
        assert returned["status"] == "RETURNED"
        demand = _get_demand(api, ctx["demand"]["id"])
        assert demand["status"] == "ISSUED", "paid_to_date back to zero"
        assert _get_store(api, store["id"])["restitution_collected_cents"] == 0, (
            "baseline restored exactly"
        )
