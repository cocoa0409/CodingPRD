"""Difficulty-design coverage.

Each instance in SCAFFOLD_DIFFICULTY_DESIGN.yaml is exercised by at least
TWO dedicated tests, tagged with the rule_id/instance.name in the docstring.
PRD-First: every assertion still cites the PRD sentence for its underlying
rule.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    ApiErrorId,
    accept_review_violation,
    advance_clock,
    appeal_violation,
    appeal_violation_payload,
    close_ranking_period,
    confirm_redemption,
    create_household,
    create_mall_item,
    create_point_rule,
    create_ranking_period,
    create_ranking_period_payload,
    create_resident,
    decide_violation,
    fetch_household,
    fetch_ranking_period,
    fetch_violation,
    fulfill_redemption,
    list_points_txns,
    make_appeal_reviewer_headers,
    make_community_admin_headers,
    make_resident_headers,
    publish_ranking_period,
    record_violation,
    return_redemption,
    setup_active_point_rule,
    setup_scoring_scenario,
    setup_ranking_window,
    setup_verified_resident,
    submit_disposal,
    submit_redemption,
    verify_resident,
    walk_violation_to_upheld,
)
from test_helpers.fixtures import create_community


# ===========================================================================
# Rule 1: dual_variant_calc
# ===========================================================================
class TestDualVariantCalc:
    def test_disposal_points_manual_vs_ai_scoring_same_inputs(self, api):
        """# difficulty: dual_variant_calc/disposal_points_manual_vs_ai_scoring

        PRD §3.3: 'Under MANUAL, the multiplier is 0.50 plus 0.50 times the
        accuracy score - linearly interpolating from 0.50 at score 0.0 to
        1.00 at score 1.0.'
        PRD §3.3: 'Under AI, the multiplier is a stepwise function: 1.00
        when the score is at least 0.80; otherwise 0.70 when the score is
        at least 0.50; otherwise 0.40.'

        Same inputs (weight=2.0, accuracy=0.5) yield different awarded
        points: MANUAL -> 15 (mult=0.75), AI -> 14 (mult=0.70).
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        d_manual = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=0.5, weight_kg=2.0,
        )
        d_ai = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="AI", accuracy_score=0.5, weight_kg=2.0,
        )
        assert d_manual["awarded_points"] == 15
        assert d_ai["awarded_points"] == 14
        assert d_manual["awarded_points"] != d_ai["awarded_points"]

    def test_disposal_points_scoring_methods_audit(self, api):
        """# difficulty: dual_variant_calc/disposal_points_manual_vs_ai_scoring

        PRD §3.3: 'Under MANUAL, the multiplier is 0.50 plus 0.50 times the
        accuracy score'. accuracy=1.0 under MANUAL gives mult=1.00. raw=20.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        d = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
        )
        assert d["awarded_points"] == 20

    def test_ranking_weekly_vs_monthly_normalization(self, api):
        """# difficulty: dual_variant_calc/ranking_score_weekly_vs_monthly_window

        PRD §3.7: 'Under WEEKLY, score equals raw_score (no normalization).
        Under MONTHLY, score equals raw_score multiplied by the canonical
        month length of 30 and divided by the number of days in the window
        (the difference in days between window_end and window_start), the
        entire expression rounded half-up to a whole integer.'

        Same 5 disposals (20 points each) in a 7-day window: WEEKLY -> 100,
        MONTHLY (same 7-day window) -> round(100 * 30/7) = round(428.57)
        = 429.
        """
        # Set up community + verified resident + rule active for both windows.
        advance_clock("2030-01-31T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        rule = setup_active_point_rule(
            community["id"], "2030-01-31T00:00:00.000Z",
            category="RECYCLABLE", base_rate_per_kg=10.00,
            daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
        )
        # 5 disposals over days 1..5 of February (in [day0=Feb1, day7=Feb8))
        for i in range(5):
            day = f"2030-02-{i+1:02d}T12:00:00.000Z"
            advance_clock(day)
            submit_disposal(
                community, household, resident,
                disposal_time=day,
                scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
            )
        # Create two periods with the same 7-day window but different granularities.
        period_week = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-02-01T00:00:00.000Z", "2030-02-08T00:00:00.000Z",
        )
        period_month = create_ranking_period(
            community["id"], "MONTHLY", "HOUSEHOLD",
            "2030-02-01T00:00:00.000Z", "2030-02-08T00:00:00.000Z",
        )
        advance_clock("2030-02-08T00:00:01.000Z")
        closed_w = close_ranking_period(community["id"], period_week["id"])
        closed_m = close_ranking_period(community["id"], period_month["id"])
        # Find entry for this household in each.
        w_entries = [
            e for e in closed_w["leaderboard"]
            if e["subject_id"] == household["id"]
        ]
        m_entries = [
            e for e in closed_m["leaderboard"]
            if e["subject_id"] == household["id"]
        ]
        assert w_entries and w_entries[0]["score"] == 100
        assert m_entries and m_entries[0]["score"] == 429
        assert w_entries[0]["score"] != m_entries[0]["score"]

    def test_ranking_yearly_normalization_uses_quality(self, api):
        """# difficulty: dual_variant_calc/ranking_score_weekly_vs_monthly_window

        PRD §3.7: 'Under YEARLY, the system computes a quality ratio: with
        denom defined as earned plus the absolute value of deducted,
        quality equals earned / denom when denom is positive and zero
        otherwise; score equals raw_score multiplied by 0.5 plus 0.5 times
        quality, rounded half-up to a whole integer.'

        Pure earned (no deductions): denom=earned, quality=1.0,
        score = round(raw * (0.5 + 0.5 * 1.0)) = round(raw).
        """
        advance_clock("2030-01-31T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        rule = setup_active_point_rule(
            community["id"], "2030-01-31T00:00:00.000Z",
            category="RECYCLABLE", base_rate_per_kg=10.00,
            daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
        )
        # 1 disposal earning 20 points in a YEARLY window.
        advance_clock("2030-02-01T12:00:00.000Z")
        submit_disposal(
            community, household, resident,
            disposal_time="2030-02-01T12:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
        )
        period = create_ranking_period(
            community["id"], "YEARLY", "HOUSEHOLD",
            "2030-02-01T00:00:00.000Z", "2030-02-08T00:00:00.000Z",
        )
        advance_clock("2030-02-08T00:00:01.000Z")
        closed = close_ranking_period(community["id"], period["id"])
        # raw=20, deducted=0, denom=20, quality=1.0
        # score = round(20*(0.5+0.5*1.0)) = round(20) = 20.
        entries = [
            e for e in closed["leaderboard"]
            if e["subject_id"] == household["id"]
        ]
        assert entries and entries[0]["score"] == 20


# ===========================================================================
# Rule 2: combinatorial_formula
# ===========================================================================
class TestCombinatorialFormula:
    def test_disposal_with_cap_overflow_split(self, api):
        """# difficulty: combinatorial_formula/disposal_points_tiered_multiplier_with_bonuses_and_cap

        PRD §3.3: 'The credited awarded_points is the minimum of raw_points
        and headroom; the difference, captured as cap_overflow_points,
        records how many raw points were dropped at the cap.'

        With daily_cap=200, 150 already credited, raw=10 -> headroom=50,
        awarded=10, cap_overflow=0.
        Then a 10-weight raw=100 disposal would have awarded=50, overflow=50.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=200,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T08:00:00.000Z",
        )
        # Burn 150 points.
        submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T08:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=15.0,
        )
        # Now headroom = 50. raw=100 -> awarded=50, overflow=50.
        d2 = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T08:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=10.0,
        )
        assert d2["awarded_points"] == 50
        assert d2["cap_overflow_points"] == 50

    def test_peak_period_bonus_combines_with_base(self, api):
        """# difficulty: combinatorial_formula/disposal_points_tiered_multiplier_with_bonuses_and_cap

        PRD §3.3: 'If the disposal's local-time hour ... falls within the
        half-open peak-period window ... the rule's peak_period_bonus_flat
        is added.' Combining base + peak bonus.

        Peak [7..10), bonus=5. base = 10*1.0*1.0 = 10, +5 peak = 15.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=7, peak_period_end_hour=10,
            peak_period_bonus_flat=5,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T08:30:00.000Z",
        )
        d = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T08:30:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=1.0,
        )
        assert d["awarded_points"] == 15

    def test_ranking_score_round_per_disposal_then_sum(self, api):
        """# difficulty: combinatorial_formula/ranking_score_per_subject_round_then_sum_order

        PRD §3.3: 'Step three: compute the base points as the rule's
        base_rate_per_kg multiplied by the effective weight in kilograms
        multiplied by the accuracy multiplier, rounded half-up to a whole
        integer. This rounding happens per disposal - it is never deferred
        to a later aggregation step.'

        base_rate=6.20, weight=2.0, mult=1.0 -> raw=12.4 -> rounded per
        disposal to 12 each. 3 disposals -> sum=36 (not 37 if sum-then-round).
        """
        advance_clock("2030-01-31T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        setup_active_point_rule(
            community["id"], "2030-01-31T00:00:00.000Z",
            category="RECYCLABLE", base_rate_per_kg=6.20,
            daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
        )
        for i in range(3):
            day = f"2030-02-{i+1:02d}T12:00:00.000Z"
            advance_clock(day)
            d = submit_disposal(
                community, household, resident,
                disposal_time=day,
                scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
            )
            assert d["awarded_points"] == 12  # round(12.4) = 12
        period = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-02-01T00:00:00.000Z", "2030-02-08T00:00:00.000Z",
        )
        advance_clock("2030-02-08T00:00:01.000Z")
        closed = close_ranking_period(community["id"], period["id"])
        entries = [
            e for e in closed["leaderboard"]
            if e["subject_id"] == household["id"]
        ]
        assert entries and entries[0]["score"] == 36

    def test_rule_effectiveness_uses_pinned_tier_not_score(self, api):
        """# difficulty: combinatorial_formula/rule_effectiveness_tier_pinned_before_score

        PRD §3.2: 'the participation tier is determined from the raw
        participation count BEFORE the weighted score is computed, and the
        score is computed using that same tier - the tier is never
        re-derived from the score itself.'

        12 households each submit 1 disposal at accuracy=0.9. After
        correcting disposal 0, that household no longer has a COMMITTED
        disposal applying this rule (PRD §3.2 defines participation by
        'at least one COMMITTED disposal'). participation=11, tier=MEDIUM
        (10 <= 11 < 50), misjudgment_ratio=1/12.
        Score = round(100*(0.4*0.9 + 0.4*(11/12) + 0.2*0.11), 1) = 74.9.
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        rule = setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            category="RECYCLABLE", base_rate_per_kg=10.00,
            daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
        )
        advance_clock("2030-01-01T01:00:00.000Z")
        from test_helpers import correct_disposal
        first_d = None
        first_hh = None
        for i in range(12):
            hh = create_household(community["id"])
            r = create_resident(community["id"], hh["id"])
            verify_resident(community["id"], hh["id"], r["id"])
            d = submit_disposal(
                {"id": community["id"]}, hh, r,
                disposal_time="2030-01-01T01:00:00.000Z",
                scoring_method="MANUAL", accuracy_score=0.9, weight_kg=1.0,
            )
            if i == 0:
                first_d = d
                first_hh = hh
        correct_disposal(
            community["id"], first_hh["id"], first_d["id"],
            accuracy_score=0.9, reason="audit re-grading",
        )
        from test_helpers import get_effectiveness
        result = get_effectiveness(community["id"], rule["id"])
        assert result["participation"] == 11
        assert result["participation_tier"] == "MEDIUM"
        assert result["score"] == pytest.approx(74.9, abs=0.05)


# ===========================================================================
# Rule 3: non_linear_state_machine
# ===========================================================================
class TestNonLinearStateMachine:
    def test_violation_cyclic_appeal_reaches_round_limit(self, api):
        """# difficulty: non_linear_state_machine/violation_cyclic_appeal_cycle

        PRD §3.6: 'The cycle UPHELD-then-APPEALED is permitted exactly once.'
        PRD §3.6: 'appeal_round is strictly less than 2 (else
        ERR_VIOLATION_REAPPEAL_LIMIT).'

        After 2 appeals (round 2), a third appeal yields the limit error.
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        # First appeal: NEW -> APPEALED -> UNDER_REVIEW -> UPHELD
        walk_violation_to_upheld(community, resident, v["id"])
        v_after_1 = fetch_violation(community["id"], v["id"])
        assert v_after_1["appeal_round"] == 1
        # Second appeal (UPHELD -> APPEALED) -> UNDER_REVIEW -> UPHELD
        walk_violation_to_upheld(community, resident, v["id"])
        v_after_2 = fetch_violation(community["id"], v["id"])
        assert v_after_2["appeal_round"] == 2
        # Third appeal must fail.
        resp = api.appeal_violation(
            community["id"], v["id"], appeal_violation_payload("third"),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_VIOLATION_REAPPEAL_LIMIT.value)

    def test_violation_state_progression_through_cycle(self, api):
        """# difficulty: non_linear_state_machine/violation_cyclic_appeal_cycle

        PRD §3.6: 'On a second appeal - current status UPHELD and appeal_round
        equal to 1 - the violation transitions UPHELD -> APPEALED.'
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        walk_violation_to_upheld(community, resident, v["id"])
        # Second appeal: UPHELD -> APPEALED, round=2.
        appealed = appeal_violation(community["id"], resident, v["id"])
        assert appealed["status"] == "APPEALED"
        assert appealed["appeal_round"] == 2

    def test_redemption_branching_to_rejected(self, api):
        """# difficulty: non_linear_state_machine/redemption_order_branching_with_revert

        PRD §3.5: 'Reject requires the order is currently SUBMITTED and
        performs no stock or points movement; it transitions to REJECTED
        (terminal).'
        """
        from test_helpers import reject_redemption_order_payload
        # Build scenario with balance.
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=10.0,
        )
        item = create_mall_item(
            scenario["community"]["id"], stock=5, cost_points=30,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=1,
        )
        resp = api.reject_redemption_order(
            scenario["community"]["id"], order["id"],
            reject_redemption_order_payload("decline"),
            make_community_admin_headers(),
        )
        data = validate_success(resp)
        assert data["status"] == "REJECTED"

    def test_redemption_branching_to_returned_re_credits(self, api):
        """# difficulty: non_linear_state_machine/redemption_order_branching_with_revert

        PRD §3.5: 'A return capability operates only on FULFILLED orders,
        requires a non-empty reason, re-credits stock by adding quantity
        back to the item, appends a PointsTransaction whose kind is
        REDEMPTION_REFUND and whose amount is the positive total_cost_points,
        and restores Household.points_balance by the same amount.'
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=10.0,
        )
        item = create_mall_item(
            scenario["community"]["id"], stock=5, cost_points=30,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=2,
        )
        confirm_redemption(scenario["community"]["id"], order["id"])
        fulfill_redemption(scenario["community"]["id"], order["id"])
        returned = return_redemption(
            scenario["community"]["id"], order["id"], "damaged",
        )
        assert returned["status"] == "RETURNED"
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        # Pre-confirm balance was 100. After confirm: 100-60=40. After
        # return: 40+60=100.
        assert hh["points_balance"] == 100


# ===========================================================================
# Rule 4: transitive_cascade
# ===========================================================================
class TestTransitiveCascade:
    def test_violation_overturn_cascade_recomputes_subsequent_and_invalidates_period(
        self, api,
    ):
        """# difficulty: transitive_cascade/violation_overturn_cascade_depth_three

        PRD §3.6: 'and then walks every subsequent Violation row - that is,
        every other violation for the same resident and the same
        violation_type whose occurred_at is strictly after this one and
        whose current status is in {NEW, APPEALED, UNDER_REVIEW, UPHELD}.
        For each such subsequent violation, the system recomputes
        repeat_count_in_window while excluding this overturned violation,
        re-derives the escalation multiplier, recomputes
        final_deduction_points, appends a PointsTransaction whose kind is
        MISJUDGMENT_ADJUSTMENT and whose amount is the old final deduction
        minus the new final deduction, and adjusts
        Household.points_balance by the same delta.'
        PRD §3.6: 'The system invalidates every OPEN-or-unpublished-CLOSED
        RankingPeriod whose window contains the original violation's
        occurred_at.'
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        # Ranking period covering the violation occurrences.
        period = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        # Three MIS_SORTING violations in escalation.
        advance_clock("2030-01-02T00:00:00.000Z")
        v1 = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        advance_clock("2030-01-03T00:00:00.000Z")
        v2 = record_violation(
            community["id"], resident["id"], "2030-01-03T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        advance_clock("2030-01-04T00:00:00.000Z")
        v3 = record_violation(
            community["id"], resident["id"], "2030-01-04T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        # v1: repeat=1 -> mult=1.00 -> final=20
        # v2: repeat=2 -> mult=1.50 -> final=30
        # v3: repeat=3 -> mult=2.00 -> final=40
        # balance = -90
        assert v1["final_deduction_points"] == 20
        assert v2["final_deduction_points"] == 30
        assert v3["final_deduction_points"] == 40
        hh_before = fetch_household(community["id"], household["id"])
        assert hh_before["points_balance"] == -90
        # Overturn v1.
        appeal_violation(community["id"], resident, v1["id"])
        accept_review_violation(community["id"], v1["id"])
        decide_violation(community["id"], v1["id"], "OVERTURN")
        # v2 and v3 must be recomputed.
        v2_after = fetch_violation(community["id"], v2["id"])
        v3_after = fetch_violation(community["id"], v3["id"])
        # v2 now has repeat=1 -> mult=1.00 -> final=20 (was 30, delta +10)
        # v3 now has repeat=2 -> mult=1.50 -> final=30 (was 40, delta +10)
        assert v2_after["final_deduction_points"] == 20
        assert v3_after["final_deduction_points"] == 30
        # Balance: -90 + 20 (reversal v1) + 10 (v2 adj) + 10 (v3 adj) = -50.
        hh_after = fetch_household(community["id"], household["id"])
        assert hh_after["points_balance"] == -50
        # RankingPeriod invalidated (leaderboard empty).
        period_after = fetch_ranking_period(community["id"], period["id"])
        assert period_after["leaderboard"] == []

    def test_violation_overturn_appends_violation_reversal_txn(self, api):
        """# difficulty: transitive_cascade/violation_overturn_cascade_depth_three

        PRD §3.6: 'the system appends a PointsTransaction whose kind is
        VIOLATION_REVERSAL and whose amount is the positive
        final_deduction_points of this violation.'
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        appeal_violation(community["id"], resident, v["id"])
        accept_review_violation(community["id"], v["id"])
        decide_violation(community["id"], v["id"], "OVERTURN")
        txns = list_points_txns(community["id"], household["id"])
        rev = [
            t for t in txns
            if t["kind"] == "VIOLATION_REVERSAL"
            and t["related_entity_id"] == v["id"]
        ]
        assert len(rev) == 1
        assert rev[0]["amount"] == 20

    def test_disposal_correction_cascade_invalidates_open_period(self, api):
        """# difficulty: transitive_cascade/disposal_correct_cascade_depth_two

        PRD §3.4: 'It invalidates every OPEN RankingPeriod whose window
        contains the disposal's disposal_time by clearing the period's
        leaderboard to the empty array.'
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        period = create_ranking_period(
            scenario["community"]["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        d = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
        )
        # Period is still OPEN; correct -> leaderboard cleared.
        from test_helpers import correct_disposal
        correct_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            accuracy_score=0.5, reason="ai re-check",
        )
        p_after = fetch_ranking_period(
            scenario["community"]["id"], period["id"],
        )
        assert p_after["leaderboard"] == []

    def test_disposal_correction_appends_misjudgment_adjustment(self, api):
        """# difficulty: transitive_cascade/disposal_correct_cascade_depth_two

        PRD §3.4: 'It appends a PointsTransaction whose kind is
        MISJUDGMENT_ADJUSTMENT and whose amount is (new_awarded_points)
        minus the old (awarded_points).'
        new awarded=15 (accuracy=0.5 -> mult=0.75, raw=15);
        delta = 15 - 20 = -5.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        d = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
        )
        from test_helpers import correct_disposal
        correct_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            accuracy_score=0.5, reason="ai re-check",
        )
        txns = list_points_txns(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        adj = [
            t for t in txns
            if t["kind"] == "MISJUDGMENT_ADJUSTMENT"
            and t["related_entity_id"] == d["id"]
        ]
        assert len(adj) == 1
        assert adj[0]["amount"] == -5


# ===========================================================================
# Rule 5: priority_pair_validation_conflict
# ===========================================================================
class TestPriorityPairValidationConflict:
    def test_appeal_invalid_state_priority_over_window_expired(self, api):
        """# difficulty: priority_pair_validation_conflict/appeal_window_expired_vs_invalid_state

        PRD §2.10: 'state-transition legality sixth (ERR_INVALID_STATE).
        Only after these structural checks pass does the system evaluate
        business rules - and those rules are themselves ordered. For
        appeals, the appeal-window check (ERR_APPEAL_WINDOW_EXPIRED) fires
        before any other business rule.'

        State check (priority 6) wins over appeal-window check (priority 7).
        Set up a violation in OVERTURNED state (terminal) and advance clock
        past appeal_deadline_at: attempt to appeal should yield
        ERR_INVALID_STATE, not ERR_APPEAL_WINDOW_EXPIRED.
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        # Drive to terminal OVERTURNED state.
        appeal_violation(community["id"], resident, v["id"])
        accept_review_violation(community["id"], v["id"])
        decide_violation(community["id"], v["id"], "OVERTURN")
        # Now advance past appeal_deadline_at and re-attempt appeal.
        advance_clock("2030-02-01T00:00:00.000Z")
        resp = api.appeal_violation(
            community["id"], v["id"], appeal_violation_payload("late"),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_confirm_insufficient_stock_priority_over_insufficient_points(
        self, api,
    ):
        """# difficulty: priority_pair_validation_conflict/insufficient_points_vs_insufficient_stock_priority

        PRD §2.10: 'for redemption confirm, the stock check
        (ERR_INSUFFICIENT_STOCK) precedes the balance check
        (ERR_INSUFFICIENT_POINTS).'

        Stock=0 AND points_balance=5 < cost=100 -> both fail; stock check
        wins.
        """
        # Build resident with very low balance (5 points).
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        # Need balance = 5: rule with base_rate=5.00, weight=1.0, accuracy=1.0.
        setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            category="RECYCLABLE", base_rate_per_kg=5.00,
            daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
        )
        advance_clock("2030-01-01T01:00:00.000Z")
        submit_disposal(
            community, household, resident,
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=1.0,
        )
        hh = fetch_household(community["id"], household["id"])
        assert hh["points_balance"] == 5
        # Create item: cost=100, stock=0.
        item = create_mall_item(
            community["id"], stock=0, cost_points=100, channel="ONLINE",
        )
        # Submit-and-confirm requires LISTED + same community (which holds);
        # stock=0 < quantity=1 AND balance=5 < cost=100. Confirm:
        # ERR_INSUFFICIENT_STOCK wins.
        # First we must increase stock to allow submit to succeed (submit
        # itself does not check stock — PRD §3.5 lists submit checks only
        # for resident-active and item-listed/same-community). Actually
        # submit does not check stock at all, so stock=0 is fine.
        order = submit_redemption(
            {"id": community["id"]}, household, resident, item, quantity=1,
        )
        resp = api.confirm_redemption_order(
            community["id"], order["id"], make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


# ===========================================================================
# Rule 6: boundary_precision_check
# ===========================================================================
class TestBoundaryPrecisionCheck:
    def test_daily_cap_exact_inclusive_yields_zero_award_overflow_full(
        self, api,
    ):
        """# difficulty: boundary_precision_check/daily_cap_exact_boundary

        PRD §3.3: 'The headroom is the maximum of zero and the rule's
        daily_cap_points minus that running sum. The credited awarded_points
        is the minimum of raw_points and headroom; the difference, captured
        as cap_overflow_points, records how many raw points were dropped at
        the cap.'

        daily_cap=200, after a 200-point soaker headroom=0. Follow-up
        raw=10 -> awarded=0, overflow=10.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=200,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T08:00:00.000Z",
        )
        # Soaker: weight=20 -> raw=200 -> awarded=200 (cap met exactly).
        soaker = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T08:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=20.0,
        )
        assert soaker["awarded_points"] == 200
        assert soaker["cap_overflow_points"] == 0
        # Follow-up: weight=1 -> raw=10 -> awarded=0, overflow=10.
        follow_up = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T08:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=1.0,
        )
        assert follow_up["awarded_points"] == 0
        assert follow_up["cap_overflow_points"] == 10
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh["points_balance"] == 200

    def test_publish_empty_ranking_period_yields_ranking_empty(self, api):
        """# difficulty: boundary_precision_check/ranking_publish_empty_leaderboard

        PRD §3.7: 'Publish requires that the period is currently CLOSED and
        that the leaderboard is non-empty (else ERR_RANKING_EMPTY).'
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        period = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        advance_clock("2030-01-08T00:00:01.000Z")
        closed = close_ranking_period(community["id"], period["id"])
        assert closed["leaderboard"] == []
        resp = api.publish_ranking_period(
            community["id"], period["id"], make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RANKING_EMPTY.value)


# ===========================================================================
# Rule 7: cross_entity_state_dependency
# ===========================================================================
class TestCrossEntityStateDependency:
    def test_disposal_requires_resident_active(self, api):
        """# difficulty: cross_entity_state_dependency/disposal_requires_resident_active_and_rule_active

        PRD §3.3: 'the resident must also have identity_status of VERIFIED
        AND account_status of ACTIVE.'
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        household = create_household(community["id"])
        resident = create_resident(community["id"], household["id"])
        # No verify -> PENDING/INACTIVE.
        setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
        )
        from test_helpers import create_disposal_payload
        payload = create_disposal_payload(
            resident_id=resident["id"],
            disposal_time="2030-01-01T00:00:00.000Z",
        )
        resp = api.create_disposal(
            community["id"], household["id"], payload,
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENT_INACTIVE.value)

    def test_disposal_requires_active_point_rule(self, api):
        """# difficulty: cross_entity_state_dependency/disposal_requires_resident_active_and_rule_active

        PRD §3.3: 'the absence of such a rule yields ERR_NO_ACTIVE_RULE.'
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        # No PointRule activated.
        from test_helpers import create_disposal_payload
        payload = create_disposal_payload(
            resident_id=resident["id"],
            disposal_time="2030-01-01T00:00:00.000Z",
        )
        resp = api.create_disposal(
            community["id"], household["id"], payload,
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RULE.value)

    def test_redemption_confirm_requires_household_balance(self, api):
        """# difficulty: cross_entity_state_dependency/redemption_confirm_requires_household_balance_and_stock

        PRD §3.5: 'Confirm requires SUBMITTED AND MallItem.stock at or
        above the order's quantity (else ERR_INSUFFICIENT_STOCK) AND
        Household.points_balance at or above total_cost_points (else
        ERR_INSUFFICIENT_POINTS).'

        Stock=10 (sufficient), balance=50 (insufficient for cost=100).
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
        )
        advance_clock("2030-01-01T01:00:00.000Z")
        submit_disposal(
            community, household, resident,
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=5.0,
        )
        # balance = 50.
        item = create_mall_item(
            community["id"], stock=10, cost_points=100, channel="ONLINE",
        )
        order = submit_redemption(
            {"id": community["id"]}, household, resident, item, quantity=1,
        )
        resp = api.confirm_redemption_order(
            community["id"], order["id"], make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)

    def test_redemption_confirm_requires_mall_item_stock(self, api):
        """# difficulty: cross_entity_state_dependency/redemption_confirm_requires_household_balance_and_stock

        PRD §3.5: 'Confirm requires ... MallItem.stock at or above the
        order's quantity (else ERR_INSUFFICIENT_STOCK).'

        Stock=0, balance plenty. After topping up: succeeds (covered by
        first sub-claim above). Here we cover the stock-failure case.
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
        )
        advance_clock("2030-01-01T01:00:00.000Z")
        submit_disposal(
            community, household, resident,
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=20.0,
        )
        # balance = 200.
        item = create_mall_item(
            community["id"], stock=0, cost_points=50, channel="ONLINE",
        )
        order = submit_redemption(
            {"id": community["id"]}, household, resident, item, quantity=1,
        )
        resp = api.confirm_redemption_order(
            community["id"], order["id"], make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)


# ===========================================================================
# Rule 8: resource_temporal_overlap
# ===========================================================================
class TestResourceTemporalOverlap:
    def test_point_rule_dual_active_for_category_rejected(self, api):
        """# difficulty: resource_temporal_overlap/point_rule_active_window_no_overlap_per_category

        PRD §3.2: 'Activation by a CommunityAdmin requires that the rule is
        currently in DRAFT and that no other PointRule with the same
        (community_id, category) is currently ACTIVE.'
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        rule_a = setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            category="RECYCLABLE",
        )
        rule_b = create_point_rule(community["id"], category="RECYCLABLE")
        from test_helpers import activate_point_rule_payload
        resp = api.activate_point_rule(
            community["id"], rule_b["id"],
            activate_point_rule_payload("2030-01-02T00:00:00.000Z"),
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RULE_ALREADY_ACTIVE.value)

    def test_point_rule_succession_after_retirement(self, api):
        """# difficulty: resource_temporal_overlap/point_rule_active_window_no_overlap_per_category

        PRD §3.2: 'a competing predecessor must be retired first or the
        activation is rejected with ERR_RULE_ALREADY_ACTIVE.'

        After retire, the successor activates successfully.
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        rule_a = setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            category="RECYCLABLE",
        )
        from test_helpers import retire_point_rule, activate_point_rule
        advance_clock("2030-02-01T00:00:00.000Z")
        retire_point_rule(community["id"], rule_a["id"])
        rule_b = create_point_rule(community["id"], category="RECYCLABLE")
        activated = activate_point_rule(
            community["id"], rule_b["id"], "2030-02-01T00:00:00.000Z",
        )
        assert activated["status"] == "ACTIVE"

    def test_ranking_period_overlap_rejected(self, api):
        """# difficulty: resource_temporal_overlap/ranking_period_no_overlap_contiguous_per_dimension

        PRD §3.7: 'period windows must not overlap any existing period.'
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        resp = api.create_ranking_period(
            community["id"],
            create_ranking_period_payload(
                "WEEKLY", "HOUSEHOLD",
                "2030-01-06T00:00:00.000Z", "2030-01-13T00:00:00.000Z",
            ),
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RANKING_PERIOD_OVERLAP.value)

    def test_ranking_period_non_contiguous_rejected_for_weekly(self, api):
        """# difficulty: resource_temporal_overlap/ranking_period_no_overlap_contiguous_per_dimension

        PRD §3.7: 'for WEEKLY and MONTHLY granularities, the new period
        must additionally be contiguous with the immediately prior period.'
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        resp = api.create_ranking_period(
            community["id"],
            create_ranking_period_payload(
                "WEEKLY", "HOUSEHOLD",
                "2030-01-10T00:00:00.000Z", "2030-01-17T00:00:00.000Z",
            ),
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RANKING_PERIOD_OVERLAP.value)


# ===========================================================================
# Rule 9: compensating_invariant
# ===========================================================================
class TestCompensatingInvariant:
    def test_redemption_confirm_then_return_conserves_balance_plus_inflight(
        self, api,
    ):
        """# difficulty: compensating_invariant/redemption_return_balance_plus_open_redemptions_invariant

        PRD §3.5: 'The compensating invariant is: between submit and confirm
        followed by return, the sum of Household.points_balance and the
        total cost across confirmed-but-not-returned orders is conserved.'
        """
        # Earn 200 points via disposal.
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=20.0,
        )
        # Now balance == 200. Q_before = 200 + 0 = 200.
        item = create_mall_item(
            scenario["community"]["id"], stock=10, cost_points=50,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=2,
        )
        # SUBMITTED: stock and balance untouched. Q == 200.
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh["points_balance"] == 200
        # Confirm: balance -= 100, in_flight += 100. Q stays 200.
        confirm_redemption(scenario["community"]["id"], order["id"])
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh["points_balance"] == 100
        fulfill_redemption(scenario["community"]["id"], order["id"])
        # After return: balance += 100, in_flight -= 100. Q stays 200.
        return_redemption(
            scenario["community"]["id"], order["id"], "wrong item",
        )
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh["points_balance"] == 200

    def test_violation_overturn_conserves_lifetime_points_earned(self, api):
        """# difficulty: compensating_invariant/violation_overturn_lifetime_disposal_points_invariant

        PRD §2.7: 'Household.lifetime_points_earned is a separate cumulative
        tracker of positive disposal credits that does NOT decrease on
        redemptions but DOES adjust under disposal correction or void.'

        Violation overturn does NOT touch lifetime_points_earned — only
        balance is affected via VIOLATION_REVERSAL.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        # Earn 60 points across 3 disposals.
        for i in range(3):
            submit_disposal(
                scenario["community"], scenario["household"],
                scenario["resident"],
                disposal_time="2030-01-01T01:00:00.000Z",
                scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
            )
        hh_after_disposals = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh_after_disposals["points_balance"] == 60
        assert hh_after_disposals["lifetime_points_earned"] == 60
        # Record violation -> debit 20.
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            scenario["community"]["id"], scenario["resident"]["id"],
            "2030-01-02T00:00:00.000Z", violation_type="MIS_SORTING",
        )
        hh_after_v = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh_after_v["points_balance"] == 40
        assert hh_after_v["lifetime_points_earned"] == 60
        # Overturn -> reversal.
        appeal_violation(
            scenario["community"]["id"], scenario["resident"], v["id"],
        )
        accept_review_violation(scenario["community"]["id"], v["id"])
        decide_violation(scenario["community"]["id"], v["id"], "OVERTURN")
        hh_after_overturn = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        # balance = 40 + 20 = 60. lifetime untouched at 60.
        assert hh_after_overturn["points_balance"] == 60
        assert hh_after_overturn["lifetime_points_earned"] == 60


# ===========================================================================
# Additional second-tests to meet the "at least TWO tests per instance" rule
# ===========================================================================
class TestDifficultySecondaryCoverage:
    """One extra test per instance that previously had only one, so every
    scaffold_difficulty_design[*].instances[*] has >= 2 tagged tests."""

    def test_ranking_score_per_subject_round_then_sum_independence_check(
        self, api,
    ):
        """# difficulty: combinatorial_formula/ranking_score_per_subject_round_then_sum_order

        PRD §3.3: 'This rounding happens per disposal - it is never deferred
        to a later aggregation step.'

        Different rate to confirm the order: base_rate=3.20, weight=2.0 ->
        raw=6.4 -> rounded to 6 per disposal. 4 disposals -> sum=24.
        Sum-then-round would yield round(25.6) = 26.
        """
        advance_clock("2030-01-31T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        setup_active_point_rule(
            community["id"], "2030-01-31T00:00:00.000Z",
            category="RECYCLABLE", base_rate_per_kg=3.20,
            daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
        )
        for i in range(4):
            day = f"2030-02-{i+1:02d}T12:00:00.000Z"
            advance_clock(day)
            d = submit_disposal(
                community, household, resident,
                disposal_time=day,
                scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
            )
            assert d["awarded_points"] == 6
        period = create_ranking_period(
            community["id"], "WEEKLY", "HOUSEHOLD",
            "2030-02-01T00:00:00.000Z", "2030-02-08T00:00:00.000Z",
        )
        advance_clock("2030-02-08T00:00:01.000Z")
        closed = close_ranking_period(community["id"], period["id"])
        entries = [
            e for e in closed["leaderboard"]
            if e["subject_id"] == household["id"]
        ]
        assert entries and entries[0]["score"] == 24

    def test_rule_effectiveness_tier_pinned_for_low_branch(self, api):
        """# difficulty: combinatorial_formula/rule_effectiveness_tier_pinned_before_score

        PRD §3.2: 'the participation tier is determined from the raw
        participation count BEFORE the weighted score is computed.'

        With only 5 households participating, tier=LOW. weights for LOW:
        accuracy 0.30, misjudgment 0.50, participation 0.20.
        avg_accuracy=1.0, misjudgment_ratio=0, participation_normalized=0.05.
        score = round(100*(0.30*1.0 + 0.50*1.0 + 0.20*0.05), 1)
              = round(100*(0.30 + 0.50 + 0.01), 1)
              = round(81.0, 1) = 81.0.
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        rule = setup_active_point_rule(
            community["id"], "2030-01-01T00:00:00.000Z",
            category="RECYCLABLE", base_rate_per_kg=10.00,
            daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
        )
        advance_clock("2030-01-01T01:00:00.000Z")
        for _ in range(5):
            hh = create_household(community["id"])
            r = create_resident(community["id"], hh["id"])
            verify_resident(community["id"], hh["id"], r["id"])
            submit_disposal(
                {"id": community["id"]}, hh, r,
                disposal_time="2030-01-01T01:00:00.000Z",
                scoring_method="MANUAL", accuracy_score=1.0, weight_kg=1.0,
            )
        from test_helpers import get_effectiveness
        result = get_effectiveness(community["id"], rule["id"])
        assert result["participation"] == 5
        assert result["participation_tier"] == "LOW"
        assert result["score"] == pytest.approx(81.0, abs=0.05)

    def test_appeal_invalid_state_priority_terminal_upheld(self, api):
        """# difficulty: priority_pair_validation_conflict/appeal_window_expired_vs_invalid_state

        PRD §2.10: 'state-transition legality sixth (ERR_INVALID_STATE).
        Only after these structural checks pass does the system evaluate
        business rules.'

        A violation locked into a non-NEW-non-UPHELD-round-1 state plus an
        expired appeal window: the state check must fire first. Here we use
        a violation already past appeal_round=2 (cycle exhausted) with
        appeal_filed_at past deadline.

        Use APPEALED state: a freshly-appealed violation is in APPEALED;
        re-appealing while still APPEALED is an invalid transition. Couple
        that with expired window -> state check wins.
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            community["id"], resident["id"], "2030-01-02T00:00:00.000Z",
            violation_type="MIS_SORTING",
        )
        appeal_violation(community["id"], resident, v["id"])
        # Now in APPEALED; advance past window.
        advance_clock("2030-02-01T00:00:00.000Z")
        resp = api.appeal_violation(
            community["id"], v["id"], appeal_violation_payload("retry"),
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_confirm_insufficient_stock_priority_zero_balance(self, api):
        """# difficulty: priority_pair_validation_conflict/insufficient_points_vs_insufficient_stock_priority

        PRD §2.10: 'for redemption confirm, the stock check
        (ERR_INSUFFICIENT_STOCK) precedes the balance check
        (ERR_INSUFFICIENT_POINTS).'

        Second variation: stock=0 AND balance=0 < cost=100 -> stock check
        wins (both fail).
        """
        # Resident with balance=0 (no disposals).
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        item = create_mall_item(
            community["id"], stock=0, cost_points=100, channel="ONLINE",
        )
        order = submit_redemption(
            {"id": community["id"]}, household, resident, item, quantity=1,
        )
        resp = api.confirm_redemption_order(
            community["id"], order["id"], make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)

    def test_daily_cap_exact_boundary_at_199(self, api):
        """# difficulty: boundary_precision_check/daily_cap_exact_boundary

        PRD §3.3: 'The credited awarded_points is the minimum of raw_points
        and headroom.' Boundary at X-1: headroom=1 after using 199, raw=10
        -> awarded=1, overflow=9.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=200,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T08:00:00.000Z",
        )
        # Burn 199: weight=19.9 -> base=10*19.9*1.0=199.
        submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T08:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=19.9,
        )
        # raw=10 -> awarded=1, overflow=9.
        d = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T08:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=1.0,
        )
        assert d["awarded_points"] == 1
        assert d["cap_overflow_points"] == 9

    def test_ranking_publish_empty_two_independent_subjects_no_data(
        self, api,
    ):
        """# difficulty: boundary_precision_check/ranking_publish_empty_leaderboard

        PRD §3.7: 'If the eligible subject set is empty (no eligible
        disposals AND no eligible violations), the leaderboard is the empty
        array.' Publish then rejects with ERR_RANKING_EMPTY.

        Second variation: BUILDING dimension with no qualifying disposals.
        """
        advance_clock("2030-01-01T00:00:00.000Z")
        community, _, _ = setup_verified_resident()
        period = create_ranking_period(
            community["id"], "WEEKLY", "BUILDING",
            "2030-01-01T00:00:00.000Z", "2030-01-08T00:00:00.000Z",
        )
        advance_clock("2030-01-08T00:00:01.000Z")
        closed = close_ranking_period(community["id"], period["id"])
        assert closed["leaderboard"] == []
        resp = api.publish_ranking_period(
            community["id"], period["id"], make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_RANKING_EMPTY.value)

    def test_redemption_invariant_after_two_distinct_orders(self, api):
        """# difficulty: compensating_invariant/redemption_return_balance_plus_open_redemptions_invariant

        PRD §3.5: 'the sum of Household.points_balance and the total cost
        across confirmed-but-not-returned orders is conserved.'

        Second observation: with TWO orders in flight, the invariant still
        holds after only one is returned.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=30.0,
        )
        # balance = 300.
        item = create_mall_item(
            scenario["community"]["id"], stock=10, cost_points=50,
        )
        o1 = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=1,
        )
        o2 = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=2,
        )
        confirm_redemption(scenario["community"]["id"], o1["id"])
        confirm_redemption(scenario["community"]["id"], o2["id"])
        # balance=300-50-100=150; in_flight=50+100=150 -> Q=300.
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh["points_balance"] == 150
        # Fulfill+return o1: balance += 50, in_flight -= 50.
        fulfill_redemption(scenario["community"]["id"], o1["id"])
        return_redemption(scenario["community"]["id"], o1["id"], "wrong size")
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh["points_balance"] == 200  # 150 + 50

    def test_violation_lifetime_invariant_after_correction_clear(self, api):
        """# difficulty: compensating_invariant/violation_overturn_lifetime_disposal_points_invariant

        PRD §2.7: 'Household.lifetime_points_earned is a separate cumulative
        tracker of positive disposal credits that does NOT decrease on
        redemptions but DOES adjust under disposal correction or void.'

        Second observation: violation creation alone (without overturn)
        keeps lifetime untouched.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=2.0,
        )
        hh_before = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh_before["points_balance"] == 20
        assert hh_before["lifetime_points_earned"] == 20
        advance_clock("2030-01-02T00:00:00.000Z")
        v = record_violation(
            scenario["community"]["id"], scenario["resident"]["id"],
            "2030-01-02T00:00:00.000Z", violation_type="MIS_SORTING",
        )
        hh_after = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        # balance debited; lifetime unchanged.
        assert hh_after["points_balance"] == 0  # 20 - 20
        assert hh_after["lifetime_points_earned"] == 20
