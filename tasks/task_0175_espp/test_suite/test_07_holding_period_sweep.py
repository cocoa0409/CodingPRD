"""Holding-period maturation: WITHIN_BOTH -> PAST_ONE_YEAR_FROM_PURCHASE
and -> QUALIFYING_MATURE driven by the sweep.

References PRD §3.6, §2.9.
"""
from __future__ import annotations

from test_helpers import (
    add_days,
    add_years,
    advance_clock_to,
    parse_iso,
    run_sweep,
    setup_purchase_after_run,
    TEST_USERS,
    validate_success,
)


class TestHoldingPeriodMaturation:
    """PRD §3.6 sweep-driven holding-period transitions."""

    def test_initial_status_is_within_both(self, api):
        """PRD §3.6: "The dimension's initial value at purchase creation
        is `WITHIN_BOTH`."

        Claim: brand-new Purchase has holding_period_status==WITHIN_BOTH.
        """
        plan, op_after, _pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        assert purchase["holding_period_status"] == "WITHIN_BOTH"
        assert purchase["disposition_status"] == "HELD"

    def test_sweep_advances_to_past_one_year_from_purchase(self, api):
        """PRD §3.6: "The sweep advances a purchase from `WITHIN_BOTH`
        to `PAST_ONE_YEAR_FROM_PURCHASE` when `SystemClock.current_time`
        has reached or passed `purchase_date` plus one year and is still
        strictly less than `grant_date` plus two years; the precondition
        for this side effect is that the purchase's `disposition_status`
        is still `HELD`."

        Claim: clock at purchase+1y (which is grant+1.5y, < grant+2y)
        -> after sweep, holding_period_status==PAST_ONE_YEAR_FROM_PURCHASE.
        """
        plan, op_after, _pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        # Anchor relative to the actual purchase_date so the test is
        # robust to clock drift from prior tests (PRD §2.9 — clock is
        # monotonic, fixture derives dates from the current clock).
        advance_clock_to(add_years(purchase["purchase_date"], 1))
        run_sweep()
        resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        data = validate_success(resp)
        assert data["holding_period_status"] == "PAST_ONE_YEAR_FROM_PURCHASE"
        assert data["disposition_status"] == "HELD"

    def test_sweep_advances_to_qualifying_mature(self, api):
        """PRD §3.6: "The sweep advances directly from `WITHIN_BOTH` to
        `QUALIFYING_MATURE` when `SystemClock.current_time` has reached
        or passed `grant_date` plus two years and has also reached or
        passed `purchase_date` plus one year".

        Claim: clock at grant+2y (which is past purchase+1y since
        purchase = grant+6mo, so grant+2y = purchase+1.5y) -> after
        sweep, holding_period_status==QUALIFYING_MATURE.
        """
        plan, op_after, _pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        # op_after.start_date is the grant_date (PRD §3.5: Form 3922's
        # grant_date is the period's start_date).
        grant_date = op_after["start_date"]
        target = add_years(grant_date, 2)
        advance_clock_to(add_days(target, 1))
        run_sweep()
        resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        data = validate_success(resp)
        assert data["holding_period_status"] == "QUALIFYING_MATURE"
        assert data["disposition_status"] == "HELD"

    def test_sweep_advances_past_one_year_to_qualifying_mature(self, api):
        """PRD §3.6: "From `PAST_ONE_YEAR_FROM_PURCHASE`, the sweep
        advances to `QUALIFYING_MATURE` once `SystemClock.current_time`
        has reached or passed `grant_date` plus two years; again, the
        purchase must still be `HELD`."

        Claim: walk WITHIN_BOTH -> PAST_ONE_YEAR_FROM_PURCHASE -> QUALIFYING_MATURE
        in two sweep steps.
        """
        plan, op_after, _pid, purchase = setup_purchase_after_run(
            grant_date_fmv_cents=1000,
            purchase_date_fmv_cents=2000,
            contribution_amount_cents=8500,
            contribution_rate_bp=1500,
        )
        # First sweep: clock at purchase+1y triggers WITHIN_BOTH -> PAST_ONE_YEAR.
        advance_clock_to(add_years(purchase["purchase_date"], 1))
        run_sweep()
        # Second sweep: clock at grant+2y triggers PAST_ONE_YEAR -> QUALIFYING_MATURE.
        grant_date = op_after["start_date"]
        target = add_years(grant_date, 2)
        advance_clock_to(add_days(target, 1))
        run_sweep()
        resp = api.get_purchase(
            purchase["id"], TEST_USERS["plan_admin_headers"],
        )
        data = validate_success(resp)
        assert data["holding_period_status"] == "QUALIFYING_MATURE"
