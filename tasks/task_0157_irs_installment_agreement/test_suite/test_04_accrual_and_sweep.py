"""Monthly accrual mechanics — PRD §3.2.

The status-branch differential is the load-bearing observation:
identical bases yield three different penalty values across OPEN /
IN_AGREEMENT / CNC liabilities.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock_to,
    get_tax_liability,
    run_sweep,
    setup_three_liabilities_for_status_branching,
)


class TestMonthlyAccrualStatusBranching:

    def test_open_liability_accrues_interest_and_full_ftp(self):
        """PRD §3.2: "it is one half of one percent (0.005) when the
        liability is OPEN."
        PRD §3.2: "the monthly interest rate (locked at 0.006667 for
        benchmark determinism, which corresponds to roughly eight
        percent on an annual basis)."

        Claim: after one EOM cycle on an OPEN $10,000 liability
        accrued_interest == round_half_up(1_000_000 * 0.006667) = 6_667
        and accrued_penalty == round_half_up(1_000_000 * 0.005) = 5_000.

        # difficulty: combinatorial_formula/monthly_accrual_status_branching
        """
        taxpayer, liab_open, liab_ia, liab_cnc, ia, cnc = (
            setup_three_liabilities_for_status_branching()
        )
        advance_clock_to("2020-01-31T23:59:59.000Z")
        run_sweep()
        refreshed = get_tax_liability(liab_open["id"])
        assert refreshed["status"] == "OPEN"
        assert refreshed["accrued_interest_cents"] == 6_667, (
            "interest = round_half_up(1_000_000 * 0.006667) = 6_667"
        )
        assert refreshed["accrued_penalty_cents"] == 5_000, (
            "OPEN penalty = round_half_up(1_000_000 * 0.005) = 5_000"
        )

    def test_in_agreement_liability_uses_half_penalty(self):
        """PRD §3.2: "exactly one quarter of one percent (0.0025) — that
        is, half the non-IA rate — when the liability is IN_AGREEMENT."

        Claim: same base, in-agreement penalty == 2_500 cents (half of
        OPEN's 5_000).

        # difficulty: combinatorial_formula/monthly_accrual_status_branching
        """
        taxpayer, liab_open, liab_ia, liab_cnc, ia, cnc = (
            setup_three_liabilities_for_status_branching()
        )
        advance_clock_to("2020-01-31T23:59:59.000Z")
        run_sweep()
        refreshed = get_tax_liability(liab_ia["id"])
        assert refreshed["status"] == "IN_AGREEMENT"
        assert refreshed["accrued_interest_cents"] == 6_667
        assert refreshed["accrued_penalty_cents"] == 2_500, (
            "IN_AGREEMENT penalty = round_half_up(1_000_000 * 0.0025) = 2_500"
        )

    def test_cnc_liability_accrues_interest_only_no_penalty(self):
        """PRD §3.2: "and zero when the liability is CNC (penalty does
        not accrue while the taxpayer is Currently Not Collectible, but
        interest continues to accrue at the same monthly interest rate)."

        Claim: CNC penalty == 0; interest still 6_667.

        # difficulty: combinatorial_formula/monthly_accrual_status_branching
        """
        taxpayer, liab_open, liab_ia, liab_cnc, ia, cnc = (
            setup_three_liabilities_for_status_branching()
        )
        advance_clock_to("2020-01-31T23:59:59.000Z")
        run_sweep()
        refreshed = get_tax_liability(liab_cnc["id"])
        assert refreshed["status"] == "CNC"
        assert refreshed["accrued_interest_cents"] == 6_667
        assert refreshed["accrued_penalty_cents"] == 0


class TestSweepIsIdempotentPerCycle:

    def test_second_sweep_in_same_cycle_does_not_double_accrue(self):
        """PRD §3.2: "the sweep walks every TaxLiability whose status is
        one of OPEN, IN_AGREEMENT, or CNC and whose
        last_accrual_cycle_date is strictly less than the end-of-month
        date under consideration."

        Claim: running the sweep twice without advancing the clock
        accrues only once for that cycle (last_accrual_cycle_date
        strict-less check).
        """
        taxpayer, liab_open, _, _, _, _ = (
            setup_three_liabilities_for_status_branching()
        )
        advance_clock_to("2020-01-31T23:59:59.000Z")
        run_sweep()
        first = get_tax_liability(liab_open["id"])
        run_sweep()
        second = get_tax_liability(liab_open["id"])
        assert (
            second["accrued_interest_cents"] == first["accrued_interest_cents"]
        ), "running the sweep again in the same cycle must not re-accrue"
        assert (
            second["accrued_penalty_cents"] == first["accrued_penalty_cents"]
        )
