"""Rent-to-own contracts: schedule rounding, delinquency/cure cycle, default with
receivable conservation, and the sweep's input-set filter (PRD §3.5, §3.7)."""
import pytest
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    setup_book, create_draft_order, get_order, get_contract,
    record_rto_payment, advance_clock, run_billing_sweep,
    drive_rto_order_to_contract, create_payment_payload,
    assert_rto_receivable_conservation, assert_rto_schedule_sums,
    RTO_TOTAL_24MO, RTO_MONTHLY_24MO, RTO_FINAL_24MO, RTO_LATE_FEE_24MO,
    RTO_CURE_PAYMENT,
)
from test_helpers import TEST_USERS

SALES = TEST_USERS["sales_rep_headers"]
FINANCE = TEST_USERS["finance_manager_headers"]


def _rto_order(api):
    jur, model, cust = setup_book()
    return create_draft_order(
        cust["id"], model["id"], jur["id"],
        options=["WINDOW"], purchase_type="RTO", rto_term_months=24,
    )


class TestRtoScheduleRoundThenRemainder:
    def test_installment_rounding_order(self, api):
        """PRD §3.7: "The installment plan is derived in a pinned order: the regular
        installment `monthly_payment_cents` is the contract total divided by the term,
        rounded half-up to whole cents, and `final_payment_cents` is whatever remains
        after the regular installment has been charged for every month but the last —
        the rounded monthly installments plus the final installment therefore always sum
        back to the contract total exactly."
        PRD §3.7: "Completing a rent-to-own order creates its `RtoContract` in `ACTIVE`,
        tied to the `order_id`, with `term_months` copied from the order and
        `total_contract_cents` equal to the RTO-variant total from §3.2."

        Design: Difficulty/combinatorial_formula/rto_schedule_round_then_remainder
        """
        order = _rto_order(api)
        _, contract = drive_rto_order_to_contract(order)
        assert contract["total_contract_cents"] == RTO_TOTAL_24MO  # 945290
        # round_half_up(945290/24) = 39387, rounded FIRST
        assert contract["monthly_payment_cents"] == RTO_MONTHLY_24MO
        # remainder-absorbing final installment: 945290 - 39387*23 = 39389
        assert contract["final_payment_cents"] == RTO_FINAL_24MO
        assert_rto_schedule_sums(contract)

    def test_contract_creation_closes_order(self, api):
        """PRD §3.5: "an order closes automatically the moment it is fully settled: for a
        cash order, when `collected_cents` minus `refunded_cents` reaches at least
        `final_total_cents`; for a rent-to-own order, the moment its contract exists in
        `ACTIVE`."
        PRD §3.7: "The `first_due_date` falls thirty days after the completion date, and
        installments come due every thirty days after that."

        Design: Difficulty/combinatorial_formula/rto_schedule_round_then_remainder
        """
        order = _rto_order(api)
        completed, contract = drive_rto_order_to_contract(order)
        assert contract["status"] == "ACTIVE"
        assert contract["term_months"] == 24
        closed = get_order(order["id"])
        assert closed["status"] == "CLOSED"
        # Completion at the startup clock 2026-08-01 -> first due 30 days later.
        assert str(contract["first_due_date"]).startswith("2026-08-31")
        assert contract["amount_applied_cents"] == 0
        assert contract["remaining_balance_cents"] == RTO_TOTAL_24MO
        assert contract["accrued_late_fees_cents"] == 0
        assert contract["written_off_cents"] == 0
        assert contract["delinquency_episodes"] == 0


class TestRtoDelinquencyCureCycle:
    def _delinquent_contract(self, api):
        order = _rto_order(api)
        _, contract = drive_rto_order_to_contract(order)
        # First due 2026-08-31; +7 grace = 2026-09-07 < 2026-09-08 -> one installment due.
        advance_clock("2026-09-08T00:00:00Z")
        run_billing_sweep()
        return order, get_contract(contract["id"])

    def test_sweep_marks_delinquent_with_late_fee(self, api):
        """PRD §3.7: "an installment counts as due once its due date plus a seven-day
        grace period falls strictly before the current logical date"
        PRD §3.7: "An `ACTIVE` contract with more installments due than covered moves
        from `ACTIVE` to `DELINQUENT`, gains one to `delinquency_episodes`, and accrues
        one late fee of ten percent of the monthly installment, rounded half-up to whole
        cents."

        Design: Difficulty/non_linear_state_machine/rto_contract_delinquency_cure_cycle
        """
        _, contract = self._delinquent_contract(api)
        assert contract["status"] == "DELINQUENT"
        assert contract["delinquency_episodes"] == 1
        # round_half_up(39387 * 0.10) = 3939
        assert contract["accrued_late_fees_cents"] == RTO_LATE_FEE_24MO

    def test_cure_payment_returns_to_active(self, api):
        """PRD §3.7: "the payment first extinguishes accrued late fees, recorded as
        `applied_to_late_fees_cents`, and the remainder reduces principal, recorded as
        `applied_to_principal_cents`."
        PRD §3.7: "When a payment on a `DELINQUENT` contract covers every past-due
        installment and every accrued late fee, the contract cures from `DELINQUENT` back
        to `ACTIVE`, with `delinquency_episodes` retained as history."

        Design: Difficulty/non_linear_state_machine/rto_contract_delinquency_cure_cycle
        """
        _, contract = self._delinquent_contract(api)
        payment = record_rto_payment(contract["id"], RTO_CURE_PAYMENT, "cure-1")
        assert payment["kind"] == "RTO_PAYMENT"
        assert payment["applied_to_late_fees_cents"] == RTO_LATE_FEE_24MO
        assert payment["applied_to_principal_cents"] == RTO_MONTHLY_24MO

        cured = get_contract(contract["id"])
        assert cured["status"] == "ACTIVE"
        assert cured["delinquency_episodes"] == 1, "episode history retained"
        assert cured["accrued_late_fees_cents"] == 0, "late fee settled by the waterfall"
        assert cured["amount_applied_cents"] == RTO_MONTHLY_24MO
        assert cured["remaining_balance_cents"] == RTO_TOTAL_24MO - RTO_MONTHLY_24MO


class TestRtoDefaultReceivableConservation:
    def _defaulted_contract(self, api):
        order = _rto_order(api)
        _, contract = drive_rto_order_to_contract(order)
        record_rto_payment(contract["id"], 20000, "rto-p1")
        advance_clock("2026-09-08T00:00:00Z")
        run_billing_sweep()  # -> DELINQUENT, one late fee
        advance_clock("2026-10-15T00:00:00Z")
        summary = run_billing_sweep()  # -> DEFAULTED + repossession
        return order, get_contract(contract["id"]), summary

    def test_default_writeoff_conserves_receivable(self, api):
        """PRD §3.7: "A `DELINQUENT` contract whose earliest uncovered due date lies at
        least forty-five days in the past — the boundary is inclusive — moves from
        `DELINQUENT` to `DEFAULTED`: its `written_off_cents` is set to the full
        `remaining_balance_cents`, the remaining balance is zeroed, and the order's
        `structure_state` moves from `INSTALLED` to `REPOSSESSION_PENDING`."
        PRD §3.7: "Throughout, applied principal plus remaining balance plus written-off
        principal always equals the contract total."

        Design: Difficulty/compensating_invariant/rto_default_receivable_conservation
        """
        _, contract, _ = self._defaulted_contract(api)
        # 2026-10-15 is exactly 45 days after the first missed due date 2026-08-31.
        assert contract["status"] == "DEFAULTED"
        assert contract["amount_applied_cents"] == 20000
        assert contract["written_off_cents"] == 925290  # 945290 - 20000
        assert contract["remaining_balance_cents"] == 0
        assert_rto_receivable_conservation(contract)

    def test_default_cascades_repossession_and_counts(self, api):
        """PRD §3.7: "After all contracts are evaluated, the sweep executes repossession:
        every order sitting in `REPOSSESSION_PENDING` moves to `REPOSSESSED`."
        PRD §3.7: "The sweep reports how many contracts were newly marked delinquent in
        `contracts_marked_delinquent` and how many were defaulted in
        `contracts_defaulted`."

        Design: Difficulty/compensating_invariant/rto_default_receivable_conservation
        """
        order, contract, summary = self._defaulted_contract(api)
        assert summary["contracts_defaulted"] == 1
        assert summary["contracts_marked_delinquent"] == 0, "already delinquent before"
        refreshed = get_order(order["id"])
        # The same sweep that defaulted the contract executes repossession afterwards.
        assert refreshed["structure_state"] == "REPOSSESSED"


def test_billing_run_skips_paid_off_contract(api):
    """PRD §3.7: "The sweep walks every contract in `ACTIVE` or `DELINQUENT` — `PAID_OFF`
    and `DEFAULTED` contracts are excluded"
    PRD §3.7: "Whenever `remaining_balance_cents` reaches zero, the contract moves to
    `PAID_OFF`, whether it was `ACTIVE` or `DELINQUENT` at the time."

    Design: Corner/calculations/billing_run_skips_paid_off_contract
    """
    order = _rto_order(api)
    _, contract = drive_rto_order_to_contract(order)
    record_rto_payment(contract["id"], RTO_TOTAL_24MO, "payoff-1", method="CHECK")
    paid_off = get_contract(contract["id"])
    assert paid_off["status"] == "PAID_OFF"
    assert paid_off["remaining_balance_cents"] == 0

    advance_clock("2026-09-08T00:00:00Z")  # past first due + grace
    summary = run_billing_sweep()
    assert summary["contracts_marked_delinquent"] == 0
    assert summary["contracts_defaulted"] == 0

    after = get_contract(contract["id"])
    assert after["status"] == "PAID_OFF", "sweep excludes PAID_OFF contracts"
    assert after["accrued_late_fees_cents"] == 0
    assert after["remaining_balance_cents"] == 0
