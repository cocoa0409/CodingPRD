"""Safe-harbor advisory — PRD §3.10.

Coverage targets:
- Response shape includes safe_harbor_met, current_tax_cents,
  payments_made_cents, threshold_current_cents, prior_threshold_cents.
- Threshold-current = ceil(current_tax * 90 / 100).
- When no prior-year accepted return exists, prior_threshold treated
  as unreachable (PRD wording).
"""
from __future__ import annotations

import math

import pytest

from test_helpers import (
    assert_safe_harbor,
    compute_tax_return,
    get_safe_harbor,
    setup_simple_w2_return,
)


# ===========================================================================
# Safe harbor — PRD §3.10
# ===========================================================================
class TestSafeHarbor:

    def test_safe_harbor_response_shape(self, api):
        """PRD §3.10: "The advisory reports safe_harbor_met as true if
        the payments meet or exceed either threshold, alongside the
        inputs (current_tax_cents, payments_made_cents,
        threshold_current_cents, prior_threshold_cents) that produced
        the verdict."

        Claim: GET /tax-returns/{id}/safe-harbor returns an object
        with all four input fields plus safe_harbor_met.
        """
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=2_500_000, federal_withholding_cents=100_000,
            filing_status="SINGLE",
        )
        compute_tax_return(taxpayer, tax_return["id"])
        advisory = get_safe_harbor(taxpayer, tax_return["id"])
        assert_safe_harbor(advisory)

    def test_threshold_current_is_90_percent_ceiling(self, api):
        """PRD §3.10: "the current-year threshold, computed as the
        current-year final tax multiplied by 90 percent with ceiling
        rounding (so the threshold is the smallest integer that is at
        least 90 percent of the current tax)".

        Claim: threshold_current_cents == ceil(current_tax_cents * 90
        / 100).
        """
        # Choose wages so taxable_income == 1_000_001 to force a
        # ceiling effect: regular_tax = floor(1_000_001 * 1000/10000) =
        # 100_000. Then 90% = 90_000 -- ceiling stays 90_000.
        # To force a true ceiling difference: choose tax such that
        # 90% has a fractional cent. Take regular_tax = 1001 cents
        # -> 90% = 900.9, ceil = 901. We synthesize via small wages.
        # SINGLE STD=1_500_000. wages=1_510_010 -> taxable=10_010 ->
        # tax=floor(10_010*1000/10000)=1001 cents.
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=1_510_010, federal_withholding_cents=0,
            filing_status="SINGLE",
        )
        compute_tax_return(taxpayer, tax_return["id"])
        advisory = get_safe_harbor(taxpayer, tax_return["id"])
        # current_tax_cents == 1001, threshold_current = ceil(1001*90/100) = 901.
        expected = math.ceil(advisory["current_tax_cents"] * 90 / 100)
        assert advisory["threshold_current_cents"] == expected, (
            f"PRD §3.10: threshold_current_cents must be "
            f"ceil(current_tax_cents * 90 / 100) = {expected}; "
            f"got {advisory['threshold_current_cents']}"
        )

    def test_no_prior_return_safe_harbor_only_via_current(self, api):
        """PRD §3.10: "When no prior-year accepted or superseded return
        exists, the prior threshold is treated as unreachable."

        Claim: when no prior-year ACCEPTED/SUPERSEDED return exists,
        the verdict cannot rely on prior_threshold — safe_harbor_met
        is true iff payments_made >= threshold_current.
        """
        # Fresh taxpayer, no prior year filings.
        taxpayer, tax_return, _ = setup_simple_w2_return(
            wages_cents=2_500_000,
            # Withholding equals current tax exactly so 100% of
            # current tax is paid in.
            federal_withholding_cents=100_000,
            filing_status="SINGLE",
        )
        compute_tax_return(taxpayer, tax_return["id"])
        advisory = get_safe_harbor(taxpayer, tax_return["id"])
        # current_tax_cents = 100_000; threshold_current = 90_000;
        # payments_made = 100_000; safe_harbor_met must be true.
        assert advisory["current_tax_cents"] == 100_000
        assert advisory["payments_made_cents"] == 100_000
        assert advisory["threshold_current_cents"] == 90_000
        assert advisory["safe_harbor_met"] is True
