"""Rule effectiveness scoring.

Covers PRD §3.2 — Rule Effectiveness (participation tier, weight vector,
weighted score) and the two evaluation-order pins (tier from raw count,
not derived from score).
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_success
from test_helpers import (
    advance_clock,
    create_household,
    create_resident,
    get_effectiveness,
    setup_active_point_rule,
    submit_disposal,
    verify_resident,
)
from test_helpers.fixtures import create_community


def _create_household_with_resident(
    community_id: str,
) -> tuple:
    hh = create_household(community_id)
    r = create_resident(community_id, hh["id"])
    verify_resident(community_id, hh["id"], r["id"])
    return hh, r


class TestRuleEffectivenessTier:
    def test_low_participation_tier_when_under_10(self, api):
        """PRD §3.2: 'LOW otherwise.' With participation < 10, tier=LOW."""
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
        # 3 households, 1 disposal each, all accuracy=1.0
        for _ in range(3):
            hh, r = _create_household_with_resident(community["id"])
            submit_disposal(
                {"id": community["id"]}, hh, r,
                disposal_time="2030-01-01T01:00:00.000Z",
                scoring_method="MANUAL", accuracy_score=1.0, weight_kg=1.0,
            )
        result = get_effectiveness(community["id"], rule["id"])
        assert result["participation"] == 3
        assert result["participation_tier"] == "LOW"

    def test_medium_participation_tier_at_10(self, api):
        """PRD §3.2: 'MEDIUM when participation is at least 10 but less
        than 50.'"""
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
        for _ in range(10):
            hh, r = _create_household_with_resident(community["id"])
            submit_disposal(
                {"id": community["id"]}, hh, r,
                disposal_time="2030-01-01T01:00:00.000Z",
                scoring_method="MANUAL", accuracy_score=1.0, weight_kg=1.0,
            )
        result = get_effectiveness(community["id"], rule["id"])
        assert result["participation"] == 10
        assert result["participation_tier"] == "MEDIUM"

    def test_score_uses_tier_from_step_b_not_redrived(self, api):
        """PRD §3.2: 'the participation tier is determined from the raw
        participation count BEFORE the weighted score is computed, and the
        score is computed using that same tier - the tier is never
        re-derived from the score itself.'

        12 households each submit 1 disposal at accuracy=0.9. Disposal 0 is
        corrected, so by PRD §3.2 ('number of distinct households with at
        least one COMMITTED disposal applying this rule') participation = 11
        — the corrected disposal's household no longer has a COMMITTED
        disposal. misjudgment_ratio = 1/12. participation_tier = MEDIUM
        (10 <= 11 < 50). Score is computed with the MEDIUM weights even
        though re-deriving from the score itself would not change tier here.
        score = round(100*(0.4*0.9 + 0.4*(1 - 1/12) + 0.2*0.11), 1) = 74.9.
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
        first_disposal_id = None
        first_hh = None
        for i in range(12):
            hh, r = _create_household_with_resident(community["id"])
            d = submit_disposal(
                {"id": community["id"]}, hh, r,
                disposal_time="2030-01-01T01:00:00.000Z",
                scoring_method="MANUAL", accuracy_score=0.9, weight_kg=1.0,
            )
            if i == 0:
                first_disposal_id = d["id"]
                first_hh = hh
        # Correct disposal 0 so misjudgment_ratio = 1/12.
        from test_helpers import correct_disposal
        correct_disposal(
            community["id"], first_hh["id"], first_disposal_id,
            accuracy_score=0.9, reason="audit re-grading",
        )
        result = get_effectiveness(community["id"], rule["id"])
        assert result["participation"] == 11
        assert result["participation_tier"] == "MEDIUM"
        assert result["score"] == pytest.approx(74.9, abs=0.05)
