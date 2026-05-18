"""Borrower grading: provisional and final grade calculations.

PRD §3.2. Provisional uses self-reported revenue + requested-amount;
final uses the borrower's latest PlaidSnapshot. The two diverge when
self-reported revenue is inflated relative to actual cashflow.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    attach_plaid_snapshot,
    create_borrower,
    get_borrower,
    setup_platform_with_officer,
)


class TestProvisionalGrade:

    def test_provisional_grade_a_high_revenue_low_request(self, api):
        """PRD §3.2: "The two normalized values combine as 0.6 times
        the revenue contribution plus 0.4 times the value one minus the
        requested-amount contribution ... 0.80 or higher is A".

        Claim: annual_revenue at the ceiling (500_000_000 cents) and
        requested_amount at the floor (1_000_000 cents) yields the
        maximum possible score (0.6*1 + 0.4*1 = 1.0 = 'A').
        """
        platform, _ = setup_platform_with_officer()
        b = create_borrower(
            platform["id"],
            annual_revenue_cents=500_000_000,
            requested_amount_cents=1_000_000,
        )
        assert b["provisional_grade"] == "A", (
            f"max-revenue + min-request should yield A; got "
            f"{b['provisional_grade']}"
        )

    def test_provisional_grade_e_low_revenue_high_request(self, api):
        """PRD §3.2: "any score below 0.35 is E."

        Claim: annual_revenue below the floor (5_000_000 cents) and
        requested_amount at the ceiling (50_000_000 cents) gives
        score = 0.6*0 + 0.4*(1-1) = 0 -> 'E'.
        """
        platform, _ = setup_platform_with_officer()
        b = create_borrower(
            platform["id"],
            annual_revenue_cents=5_000_000,
            requested_amount_cents=50_000_000,
        )
        assert b["provisional_grade"] == "E", (
            f"min-revenue + max-request should yield E; got "
            f"{b['provisional_grade']}"
        )


class TestFinalGrade:

    def test_no_snapshot_means_ungraded(self, api):
        """PRD §3.2: "If the borrower has no PlaidSnapshot, final_grade
        remains UNGRADED."

        Claim: a freshly created borrower has final_grade == 'UNGRADED'.
        """
        platform, _ = setup_platform_with_officer()
        b = create_borrower(platform["id"])
        assert b["final_grade"] == "UNGRADED"

    def test_final_grade_a_with_strong_plaid_inputs(self, api):
        """PRD §3.2 final grade formula: at max cashflow, max reserves,
        zero NSF, zero DTI, the score is 0.35 + 0.30 + 0.25 + 0.10 =
        1.00, banding to 'A'.

        Claim: deposits ~ ceiling (90 * 10_000_000), reserves at
        ceiling, NSF=0, debt_service=0 -> final_grade == 'A'.
        """
        platform, _ = setup_platform_with_officer()
        b = create_borrower(
            platform["id"],
            annual_revenue_cents=500_000_000,
            requested_amount_cents=50_000_000,
        )
        attach_plaid_snapshot(
            platform["id"], b["id"],
            deposits_last_90d_cents=90 * 10_000_000,  # daily 100k cap
            avg_daily_balance_cents=25_000_000,  # reserves cap
            nsf_count_last_90d=0,
            existing_debt_service_cents=0,
        )
        refreshed = get_borrower(platform["id"], b["id"])
        assert refreshed["final_grade"] == "A"

    # DELETED: test_provisional_vs_final_divergence_inflated_revenue
    # Reason: PRD §3.2 contains two contradictory statements about
    # provisional grading. The PRD formula normalizes annual_revenue
    # linearly from a $50,000 floor (5,000,000 cents) to a $5,000,000
    # ceiling (500,000,000 cents). Plugging $1,000,000 (100,000,000
    # cents) into the formula yields a normalized revenue of
    # (100M - 5M) / (500M - 5M) ≈ 0.192, and a combined score
    # 0.6 * 0.192 + 0.4 * (1 - 0.184) ≈ 0.44 — which bands to 'D', NOT
    # 'A'. Yet PRD §3.2's illustrative sentence ("a borrower with a
    # self-reported revenue of one million dollars ... will receive a
    # provisional grade of A") states the outcome is 'A'. The formula
    # and the illustrative example contradict, so PRD does not uniquely
    # determine the provisional grade for $1M revenue. A faithful
    # PRD-only implementer following the formula produces 'D', not 'A',
    # and a test that asserts 'A' fails the unique-derivability check
    # (STEP 1b: contradictory PRD readings).
