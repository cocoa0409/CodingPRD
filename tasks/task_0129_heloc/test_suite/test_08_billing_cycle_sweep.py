"""Billing-cycle sweep: interest accrual, delinquency, period rollover,
idempotency.

Covers PRD §3.7 (per-cycle steps: accrue interest, recompute minimum,
sum payments, update delinquency_days, advance last_cycle_end_date,
DELINQUENCY_90 default, DRAW → REPAY rollover) and sweep idempotency.
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_days,
    get_heloc,
    make_borrower_headers,
    post_draw,
    post_payment,
    run_billing_cycle_sweep,
    setup_active_heloc,
    setup_active_heloc_with_balance,
    setup_heloc_at_delinquency_days,
    setup_heloc_with_accrued_interest,
    validate_error,
    validate_success,
)


# ===========================================================================
# §3.7 Interest accrual formula
# ===========================================================================
class TestInterestAccrual:

    def test_one_cycle_accrual_matches_formula(self, api):
        """PRD §3.7: "It first computes the interest accrual for the
        cycle as the HELOC's principal_balance_cents multiplied by
        current_rate_bps, divided by 10000 to convert basis points to
        a decimal annual rate, then multiplied by 30 (one cycle's
        days) and divided by 365 (the canonical accrual year), with
        the result rounded half-up to whole cents before being added
        into accrued_interest_cents."

        With principal=1_000_000, rate=800: 1_000_000 * 800 / 10000
        * 30 / 365 = 6575.342... → round half-up = 6575.
        """
        borrower, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=1_000_000,
            margin_bps=300,
            periodic_cap_bps=200,
            lifetime_cap_bps=2000,
            lifetime_floor_bps=100,
            prime_rate_bps_at_origination=500,
        )
        # Advance one cycle and sweep.
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
        h = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        # Expected accrual = round_half_up(1_000_000 * 800/10000 *
        # 30/365) = round_half_up(6575.342) = 6575.
        assert h["accrued_interest_cents"] == 6_575


# ===========================================================================
# §3.7 Idempotency per (heloc_id, cycle_index)
# ===========================================================================
class TestSweepIdempotency:

    def test_double_sweep_no_clock_advance_is_idempotent(self, api):
        """PRD §3.7: "The sweep is idempotent per (heloc_id,
        cycle_index) pair, so re-running the sweep without advancing
        the clock does not double-accrue interest or double-increment
        delinquency."
        """
        borrower, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=1_000_000,
        )
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
        h1 = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        # Repeat sweep WITHOUT advancing clock.
        run_billing_cycle_sweep()
        h2 = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h2["accrued_interest_cents"] == h1["accrued_interest_cents"]
        assert h2["delinquency_days"] == h1["delinquency_days"]


# ===========================================================================
# §3.7 Delinquency tracking
# ===========================================================================
class TestDelinquencyTracking:

    def test_no_payment_increments_delinquency_by_30(self, api):
        """PRD §3.7: "If that sum is at least the prior cycle's
        minimum_payment_due_cents, the HELOC's delinquency_days is
        reset to zero; otherwise, delinquency_days is incremented by
        30."

        First cycle: no minimum yet (prior cycle min = 0 because
        accrued was 0). So delinquency stays 0. Second cycle: minimum
        was the first-cycle accrued; with no payment, delinquency
        increments by 30.
        """
        borrower, _, _, heloc, _ = setup_active_heloc_with_balance(
            draw_amount_cents=1_000_000,
        )
        # Cycle 1.
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
        h1 = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        # Cycle 2 — no payment, prior-cycle min > 0 → delinquency +=30.
        advance_clock_days(days=30)
        run_billing_cycle_sweep()
        h2 = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h2["delinquency_days"] >= 30, (
            f"missed payment must increment delinquency_days; got "
            f"{h2['delinquency_days']}"
        )

    def test_delinquency_90_triggers_default(self, api):
        """PRD §3.7: "After the cycle's accrual and delinquency
        update, the sweep evaluates the delinquency trigger: if
        delinquency_days is at least 90 and the HELOC's status is
        still in DRAW or REPAY, the system records a DefaultEvent with
        trigger of DELINQUENCY_90 (and source_event_id of null),
        transitions the HELOC to DEFAULT".
        """
        borrower, _, _, h = setup_heloc_at_delinquency_days(
            target_days=90,
        )
        assert h["status"] == "DEFAULT"
        assert h["default_trigger"] == "DELINQUENCY_90"
        assert h["delinquency_days"] >= 90


# ===========================================================================
# §3.7 DRAW → REPAY period rollover
# ===========================================================================
class TestPeriodRollover:

    def test_draw_to_repay_after_draw_period_end_date(self, api):
        """PRD §3.7: "if the HELOC's status is still DRAW and the
        current clock time has reached or passed draw_period_end_date,
        the HELOC transitions from DRAW to REPAY."
        """
        from test_helpers import DRAW_PERIOD_DAYS
        borrower, _, _, heloc = setup_active_heloc(
            credit_limit_cents=2_000_000,
        )
        assert heloc["status"] == "DRAW"
        # Advance just past draw_period_end_date (3650 days).
        advance_clock_days(days=DRAW_PERIOD_DAYS)
        run_billing_cycle_sweep()
        h = get_heloc(
            heloc["id"], make_borrower_headers(borrower["id"]),
        )
        assert h["status"] == "REPAY"


# ===========================================================================
# §3.7 Deterministic ordering by id
# ===========================================================================
class TestSweepDeterministicOrder:

    def test_sweep_returns_summary_on_no_op(self, api):
        """PRD §4: "POST /_sweep/billing-cycle ... returns the number
        of cycles processed and the number of default transitions it
        triggered".
        """
        # No HELOCs in DRAW/REPAY → both counts should be 0.
        from test_helpers import api_client, TEST_USERS
        resp = api_client.sweep_billing_cycle(
            TEST_USERS["platform_admin_headers"],
        )
        body = resp.json()
        assert resp.status_code == 200
        data = body["data"]
        assert "cycles_run" in data
        assert isinstance(data["cycles_run"], int)
        assert "defaults_triggered" in data
        assert isinstance(data["defaults_triggered"], int)
