"""Disposal scoring math: MANUAL/AI/SCALE multipliers, peak period,
consecutive bonus, daily cap, volume-to-weight conversion.

Covers PRD §3.3 — Disposal Submission and Points Award.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_success
from test_helpers import (
    advance_clock,
    create_disposal_payload,
    list_points_txns,
    make_resident_headers,
    setup_scoring_scenario,
    setup_with_daily_cap_burned,
    submit_disposal,
)
from test_helpers import api_client as api_singleton


class TestAccuracyMultiplier:
    def test_manual_multiplier_linear_at_half(self, api):
        """PRD §3.3: 'Under MANUAL, the multiplier is 0.50 plus 0.50 times
        the accuracy score - linearly interpolating from 0.50 at score 0.0
        to 1.00 at score 1.0.'

        accuracy=0.5 -> mult=0.75. base=10*2.0*0.75=15.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            category_bonus_flat=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        d = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=0.5, weight_kg=2.0,
        )
        assert d["awarded_points"] == 15

    def test_ai_multiplier_stepwise_at_0_50_yields_0_70(self, api):
        """PRD §3.3: 'Under AI, the multiplier is a stepwise function: 1.00
        when the score is at least 0.80; otherwise 0.70 when the score is
        at least 0.50; otherwise 0.40.'

        accuracy=0.50 -> mult=0.70. base=10*2.0*0.70=14.
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
            scoring_method="AI", accuracy_score=0.5, weight_kg=2.0,
        )
        assert d["awarded_points"] == 14

    def test_ai_multiplier_at_0_80_yields_1_00(self, api):
        """PRD §3.3: 'Under AI ... 1.00 when the score is at least 0.80.'
        accuracy=0.80 -> mult=1.00. base=10*2.0*1.00=20."""
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
            scoring_method="AI", accuracy_score=0.80, weight_kg=2.0,
        )
        assert d["awarded_points"] == 20

    def test_ai_multiplier_below_0_50_yields_0_40(self, api):
        """PRD §3.3: 'otherwise 0.40.' accuracy=0.30 -> mult=0.40.
        base=10*2.0*0.40=8."""
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
            scoring_method="AI", accuracy_score=0.30, weight_kg=2.0,
        )
        assert d["awarded_points"] == 8

    def test_scale_multiplier_always_one(self, api):
        """PRD §3.3: 'Under SCALE, the multiplier is always 1.00 regardless
        of the accuracy score.'  accuracy=0.20 still yields mult=1.00.
        base=10*2.0*1.00=20."""
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
            scoring_method="SCALE", accuracy_score=0.20, weight_kg=2.0,
        )
        assert d["awarded_points"] == 20


class TestPeakPeriodBonus:
    def test_disposal_inside_peak_window_adds_flat_bonus(self, api):
        """PRD §3.3: 'If the disposal's local-time hour (the hour-of-day in
        the community timezone) falls within the half-open peak-period
        window - at or after peak_period_start_hour and strictly before
        peak_period_end_hour - the rule's peak_period_bonus_flat is added.'

        Rule: peak [7..9), bonus=5. Disposal at 08:00 UTC -> hour=8 -> inside.
        base=10*1.0*1.0=10, +5 peak. awarded=15.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=7, peak_period_end_hour=9,
            peak_period_bonus_flat=5,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T08:00:00.000Z",
        )
        d = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T08:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=1.0,
        )
        assert d["awarded_points"] == 15

    def test_disposal_at_end_hour_excluded_from_peak(self, api):
        """PRD §3.3: 'half-open peak-period window - at or after
        peak_period_start_hour and strictly before peak_period_end_hour.'

        Rule: peak [7..9). Disposal at 09:00 UTC -> hour=9 -> excluded.
        base=10*1.0*1.0=10, no peak. awarded=10.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=7, peak_period_end_hour=9,
            peak_period_bonus_flat=5,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T09:30:00.000Z",
        )
        d = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T09:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=1.0,
        )
        assert d["awarded_points"] == 10


class TestVolumeToWeight:
    def test_volume_converts_by_category_recyclable(self, api):
        """PRD §3.3: 'multiply it by the category-specific conversion
        constant - 0.150 kg per liter for RECYCLABLE.'

        volume=10.0L * 0.150 = 1.500 kg. base=10*1.500*1.0=15.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        payload = create_disposal_payload(
            resident_id=scenario["resident"]["id"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0,
            actual_category="RECYCLABLE",
        )
        payload.pop("weight_kg")
        payload["weight_kg"] = None
        payload["volume_liters"] = 10.0
        resp = api.create_disposal(
            scenario["community"]["id"], scenario["household"]["id"], payload,
            make_resident_headers(scenario["resident"]["id"]),
        )
        d = validate_success(resp, expected_status=201)
        assert d["awarded_points"] == 15

    def test_volume_converts_for_kitchen_higher_density(self, api):
        """PRD §3.3: '0.800 kg per liter for KITCHEN.'

        volume=2.5L * 0.800 = 2.000 kg. base=10*2.000*1.0=20.
        """
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            category="KITCHEN",
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        payload = create_disposal_payload(
            resident_id=scenario["resident"]["id"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0,
            declared_category="KITCHEN", actual_category="KITCHEN",
        )
        payload.pop("weight_kg")
        payload["weight_kg"] = None
        payload["volume_liters"] = 2.5
        resp = api.create_disposal(
            scenario["community"]["id"], scenario["household"]["id"], payload,
            make_resident_headers(scenario["resident"]["id"]),
        )
        d = validate_success(resp, expected_status=201)
        assert d["awarded_points"] == 20


class TestDailyCap:
    def test_below_cap_full_award(self, api):
        """PRD §3.3: 'The credited awarded_points is the minimum of
        raw_points and headroom.' With daily_cap=200 and 0 used, raw=50
        -> awarded=50, cap_overflow=0."""
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=200,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        d = submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=5.0,
        )
        assert d["awarded_points"] == 50
        assert d["cap_overflow_points"] == 0


class TestPointsTransactionAppended:
    def test_disposal_commit_appends_disposal_credit_txn(self, api):
        """PRD §3.3: 'Append a PointsTransaction whose kind is
        DISPOSAL_CREDIT, whose amount equals awarded_points, whose
        related_entity_kind is DISPOSAL, and whose related_entity_id is
        the disposal's id.'"""
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
        txns = list_points_txns(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        credit = [
            t for t in txns
            if t["kind"] == "DISPOSAL_CREDIT"
            and t["related_entity_id"] == d["id"]
        ]
        assert len(credit) == 1
        assert credit[0]["amount"] == d["awarded_points"]
        assert credit[0]["related_entity_kind"] == "DISPOSAL"
