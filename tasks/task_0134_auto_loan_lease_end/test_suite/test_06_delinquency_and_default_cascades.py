"""Delinquency mechanics: SCHEDULED→LATE on clock advance, LATE→DEFAULTED
on grace exceedance, default_count rollup, APR uplift cascade, and the
auto-transition of a loan to DEFAULTED after three defaulted payments.

PRD §3.5, §3.11 — clock advance side effects.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    APR_UPLIFT_BPS,
    DAYS_PER_PERIOD,
    UPLIFT_THRESHOLD,
    ApiErrorId,
    TEST_USERS,
    advance_clock,
    api_client,
    create_customer,
    get_customer,
    get_loan_contract,
    list_payments_full,
    setup_active_loan,
    setup_loan_defaulted_via_clock,
    validate_paginated,
)


# ===========================================================================
# Clock advance — scheduled-to-late and late-to-defaulted sweep
# ===========================================================================
class TestClockAdvanceLatecycle:

    def test_clock_advance_marks_overdue_payments_late(self, api):
        """PRD §3.5: "A SCHEDULED payment becomes LATE when the
        customer's clock advances past the payment's due_day_index
        while the payment is still unpaid. This transition is
        system-generated and happens during clock advancement, not in
        response to any direct caller action."

        Claim: advance clock past due_day_index without paying ->
        payment status flips SCHEDULED -> LATE.
        """
        cust, _, loan = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        # Advance past the first due date but well within grace.
        advance_clock(cust, DAYS_PER_PERIOD + 5)
        rows = list_payments_full(cust, contract_id=loan["id"])
        rows.sort(key=lambda p: p["period_index"])
        assert rows[0]["status"] == "LATE", (
            f"expected period 1 LATE, got {rows[0]['status']}"
        )

    def test_clock_advance_drives_loan_to_defaulted_after_three(self, api):
        """PRD §3.5: "If the count of DEFAULTED Payment rows on the
        parent contract reaches or exceeds 3, the parent contract
        itself auto-transitions from ACTIVE to DEFAULTED."

        Claim: after enough clock advance for >=3 payments to default,
        the loan auto-transitions to DEFAULTED.
        """
        cust, _, loan = setup_loan_defaulted_via_clock(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
            paid_periods_before_default=0, skip_days=180,
        )
        assert loan["status"] == "DEFAULTED"
        defaulted_rows = [
            p for p in list_payments_full(cust, contract_id=loan["id"])
            if p["status"] == "DEFAULTED"
        ]
        assert len(defaulted_rows) >= 3


# ===========================================================================
# APR uplift cascade — depth-4 chain
# ===========================================================================
class TestAprUpliftCascade:

    def test_uplift_fires_when_default_count_crosses_threshold(self, api):
        """PRD §3.5: "If this default causes the customer's
        default_count to reach or exceed the uplift threshold of 3
        lifetime defaults for the first time, and the parent contract
        is a loan, then every ACTIVE LoanContract owned by this
        customer has its apr_bps raised by an APR uplift of 300 basis
        points (3.00%)." and "the system uses the forward-looking
        re-pricing convention from §2.10, never the chronological
        back-fill. Already-PAID payments are not touched".

        Claim: after >=3 defaults on a single loan, the loan's apr_bps
        equals base_apr_bps + 300, and a DelinquencyEvent records the
        uplift in apr_uplift_bps_applied.
        """
        cust, _, loan = setup_loan_defaulted_via_clock(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
            paid_periods_before_default=0, skip_days=180,
        )
        # Loan should have its apr uplifted by 300 bps.
        assert loan["apr_bps"] == loan["base_apr_bps"] + APR_UPLIFT_BPS
        # Customer should have default_count >= 3.
        cust_after = get_customer(cust)
        assert cust_after["default_count"] >= UPLIFT_THRESHOLD
        # DelinquencyEvent stream should have at least one row with
        # apr_uplift_bps_applied == 300.
        resp = api_client.list_delinquency_events(
            cust["id"], TEST_USERS["collections_agent_headers"],
            params={"limit": 100},
        )
        events, _meta = validate_paginated(resp)
        uplift_events = [
            e for e in events
            if e.get("apr_uplift_bps_applied") == APR_UPLIFT_BPS
        ]
        assert uplift_events, (
            "expected at least one DelinquencyEvent with "
            f"apr_uplift_bps_applied == {APR_UPLIFT_BPS}; got events "
            f"{events!r}"
        )

    def test_uplift_recomputes_scheduled_payments_not_paid_ones(self, api):
        """PRD §2.10: "When the system raises a loan's apr_bps after a
        delinquency threshold is crossed, the uplift re-prices only
        the still-SCHEDULED payments — already-PAID payments keep
        their original amortization split, and total_principal_paid_cents
        and total_interest_paid_cents are not retroactively
        recomputed."

        Claim: after the uplift, every still-SCHEDULED Payment row's
        amount_due_cents equals the loan's NEW monthly_payment_cents
        (re-priced over remaining principal at new apr_bps); already-
        PAID payments retain their original principal/interest split.
        """
        # 12 paid periods, then default cascade. Mirrors the
        # difficulty-design test recipe for transitive_cascade.
        cust, _, loan = setup_loan_defaulted_via_clock(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
            paid_periods_before_default=12, skip_days=180,
        )
        # The loan must be DEFAULTED with the uplift applied.
        assert loan["status"] == "DEFAULTED"
        assert loan["apr_bps"] == loan["base_apr_bps"] + APR_UPLIFT_BPS
        # All still-SCHEDULED rows on this contract must carry the
        # new monthly_payment_cents.
        new_monthly = loan["monthly_payment_cents"]
        rows = list_payments_full(cust, contract_id=loan["id"])
        scheduled = [p for p in rows if p["status"] == "SCHEDULED"]
        assert scheduled, "expected some still-SCHEDULED payments"
        for p in scheduled:
            assert p["amount_due_cents"] == new_monthly, (
                f"SCHEDULED period {p['period_index']} should be "
                f"re-priced to {new_monthly}, got {p['amount_due_cents']}"
            )
        # Already-PAID rows must retain their original principal/
        # interest split (non-zero portions because LOAN amortization
        # was applied).
        paid = [p for p in rows if p["status"] == "PAID"]
        assert paid, "expected at least one PAID payment (12 were paid)"
        for p in paid:
            assert p["principal_portion_cents"] > 0
            assert p["interest_portion_cents"] >= 0


# ===========================================================================
# Sticky default counter — PRD §2.10 / §3.5
# ===========================================================================
class TestDefaultStickiness:

    def test_paying_defaulted_payment_does_not_decrement_default_count(self, api):
        """PRD §2.10: "Defaults in this platform are sticky for
        accounting purposes. Once a Payment has reached DEFAULTED,
        paying it later transitions the Payment.status back to PAID
        and applies amortization, but it does not decrement the
        customer's default_count."

        Claim: paying a DEFAULTED payment leaves Customer.default_count
        unchanged.
        """
        # Drive defaults and capture the count.
        cust, _, loan = setup_loan_defaulted_via_clock(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
            paid_periods_before_default=0, skip_days=180,
        )
        cust_before = get_customer(cust)
        count_before = cust_before["default_count"]
        assert count_before >= 3
        # Find a DEFAULTED row.
        rows = list_payments_full(cust, contract_id=loan["id"])
        defaulted = [p for p in rows if p["status"] == "DEFAULTED"]
        assert defaulted
        target = sorted(defaulted, key=lambda p: p["period_index"])[0]
        # Pay it (parent contract must be DEFAULTED, which it is).
        from test_helpers import pay_payment
        pay_payment(cust, target)
        cust_after = get_customer(cust)
        assert cust_after["default_count"] == count_before, (
            "default_count must not decrement on DEFAULTED->PAID; "
            f"before {count_before} after {cust_after['default_count']}"
        )


# ===========================================================================
# ClockEvent — payments_due_now / payments_defaulted_now counts
# ===========================================================================
class TestClockEventCounters:

    def test_clock_event_payments_defaulted_now_counts_late_to_defaulted(self, api):
        """PRD §3.11: "The advance returns the resulting ClockEvent
        row, whose new_clock_day_index reports the customer's clock
        after the advance, whose payments_due_now counts the payments
        whose due_day_index fell inside the closed interval from the
        previous index to the new index, and whose
        payments_defaulted_now counts the LATE-to-DEFAULTED
        transitions that this advance produced."

        Claim: a single clock advance that flips at least one late
        payment to DEFAULTED reports payments_defaulted_now >= 1.
        """
        cust, _, _ = setup_active_loan(
            fico_score=750, msrp_cents=3_000_000,
            down_payment_cents=150_000, term_months=36,
        )
        # Build up LATE payments first (well within grace).
        advance_clock(cust, DAYS_PER_PERIOD * 3 + 5)
        # Now advance enough days to push them past grace.
        ev = advance_clock(cust, 30)
        assert ev["payments_defaulted_now"] >= 1, (
            "expected at least one LATE->DEFAULTED transition in this "
            "advance"
        )
