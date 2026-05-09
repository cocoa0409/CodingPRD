"""Ranking calculation, completion, and prize distribution
(PRD §3.5, §3.6)."""
from __future__ import annotations

import pytest

from test_helpers import (
    assert_prize_payment,
    assert_prize_payment_arithmetic,
    add_seconds,
    advance_clock,
    event_completed,
    find_participant_by_rank,
    find_payment_for_participant,
    list_participants,
    list_prize_payments,
    list_rankings,
    parse_iso,
    setup_round_robin_4_with_complete,
    setup_single_elim_8_with_complete,
    validate_success,
)


# ===========================================================================
# 3.6 — /complete creates PrizePayment rows; final_rank populated.
# ===========================================================================
class TestCompleteAndPayments:
    def test_complete_populates_final_rank(self, api):
        """PRD §3.6: 'On completion the system runs the final-variant
        ranking calculation, sets each RankingEntry.final_rank to its
        current provisional_rank, copies that rank onto each
        participant's final_rank field.'"""
        completed, parts, _ = setup_round_robin_4_with_complete()
        # Re-fetch participants — final_rank must be populated for all.
        live = list_participants(completed["id"])
        for p in live:
            assert p["final_rank"] is not None and p["final_rank"] >= 1, (
                f"Participant {p['id']}: final_rank should be set after "
                f"completion (got {p['final_rank']})"
            )

    def test_prize_payment_rows_created_for_top_8(self, api):
        """PRD §3.6: 'creates the corresponding `PrizePayment` rows.'
        PRD §3.6: 'Rank 1 receives 50% of the prize pool. Rank 2
        receives 25%. Each of ranks 3 and 4 receives 10%. Each of
        ranks 5, 6, 7, and 8 receives 1.25%. Participants whose
        `final_rank` is greater than 8 receive 0.'"""
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=0.0
        )
        payments = list_prize_payments(completed["id"])
        assert len(payments) >= 8, (
            "PRD §3.6: 8 PrizePayment rows must be created for ranks 1..8."
        )
        for p in payments:
            assert_prize_payment(p)


# ===========================================================================
# 3.6 — Tier percentages
# ===========================================================================
class TestPrizeTierPercentages:
    def test_rank_1_receives_50_percent(self, api):
        """PRD §3.6: 'Rank 1 receives 50% of the prize pool.'"""
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=0.0
        )
        live = list_participants(completed["id"])
        rank1 = find_participant_by_rank(live, 1)
        assert rank1 is not None, "Setup failed: no rank-1 participant"
        payments = list_prize_payments(completed["id"])
        pay1 = find_payment_for_participant(payments, rank1["id"])
        assert pay1 is not None
        # 50% of 10000 = 5000; residual cent (if any) accumulates to rank 1.
        assert pay1["gross_amount_cents"] == 5000

    def test_rank_2_receives_25_percent(self, api):
        """PRD §3.6: 'Rank 2 receives 25%.'"""
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=0.0
        )
        live = list_participants(completed["id"])
        rank2 = find_participant_by_rank(live, 2)
        if rank2 is None:
            pytest.skip("Setup did not produce a unique rank-2 participant.")
        payments = list_prize_payments(completed["id"])
        pay2 = find_payment_for_participant(payments, rank2["id"])
        assert pay2 is not None
        assert pay2["gross_amount_cents"] == 2500


# ===========================================================================
# 3.6 — Net = gross - tax - forfeit, clamped at 0
# ===========================================================================
class TestNetArithmetic:
    def test_net_amount_arithmetic_holds(self, api):
        """PRD §3.6: 'The net is the gross minus tax withheld minus
        forfeit, clamped at a non-negative floor of 0.'"""
        completed, parts, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=10.0
        )
        payments = list_prize_payments(completed["id"])
        for p in payments:
            assert_prize_payment_arithmetic(p)


# ===========================================================================
# 3.6 — scheduled_pay_at = starts_at + 7 days
# ===========================================================================
class TestScheduledPayAt:
    def test_scheduled_pay_at_equals_starts_at_plus_7_days(self, api):
        """PRD §3.6: 'Its scheduled_pay_at equals Event.starts_at plus 7
        days (in seconds: 604800).'"""
        completed, _, _ = setup_single_elim_8_with_complete(
            prize_pool_cents=10_000, tax_withholding_pct=0.0
        )
        payments = list_prize_payments(completed["id"])
        starts = parse_iso(completed["starts_at"])
        for p in payments:
            sched = parse_iso(p["scheduled_pay_at"])
            delta = (sched - starts).total_seconds()
            assert int(delta) == 7 * 24 * 3600, (
                f"PRD §3.6: scheduled_pay_at must be starts_at + 7 days "
                f"(604800 s); delta was {delta} for payment {p['id']}"
            )


# ===========================================================================
# 3.5 — Points formulas
# ===========================================================================
class TestPointsFormula:
    def test_round_robin_3_points_for_win(self, api):
        """PRD §3.5: 'For ROUND_ROBIN, a participant earns 3 points for
        each match they win, 1 point for each match in which
        locked_home_score equals locked_away_score (a draw), and 0
        otherwise.'

        PRD §3.2 builds a single-elimination bracket of size 2^ceil(log2(N))
        for every event_type. For N=4 the bracket has 4 slots and rank-1
        plays exactly 2 LOCKED matches (a round-1 match and the final),
        winning both → 2 * 3 = 6 points under the ROUND_ROBIN rule.
        """
        completed, parts, _ = setup_round_robin_4_with_complete()
        rankings = list_rankings(completed["id"])
        live = list_participants(completed["id"])
        rank1 = find_participant_by_rank(live, 1)
        assert rank1 is not None, (
            "Setup must produce a rank-1 participant for ROUND_ROBIN of 4."
        )
        rank1_entry = next((r for r in rankings
                            if r["participant_id"] == rank1["id"]), None)
        assert rank1_entry is not None
        # rank-1 wins 2 matches in a 4-slot bracket → 6 points (3 per win).
        assert rank1_entry["points"] == 6
