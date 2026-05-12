"""Disposal correction and void.

Covers PRD §3.4 — recompute against the pinned applied_rule_id,
MISJUDGMENT_ADJUSTMENT signed delta, lifetime_points_earned adjustment.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    ApiErrorId,
    correct_disposal,
    correct_disposal_payload,
    fetch_disposal,
    fetch_household,
    list_audit_logs,
    list_points_txns,
    make_community_admin_headers,
    setup_scoring_scenario,
    submit_disposal,
    void_disposal,
    void_disposal_payload,
)


class TestCorrect:
    def test_correct_committed_disposal_transitions_to_corrected(self, api):
        """PRD §3.4: 'The disposal transitions COMMITTED -> CORRECTED.'"""
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
        # Now correct it.
        corrected = correct_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            accuracy_score=0.5,
            reason="re-graded after audit",
        )
        assert corrected["status"] == "CORRECTED"

    def test_correct_appends_misjudgment_adjustment_with_signed_delta(self, api):
        """PRD §3.4: 'It appends a PointsTransaction whose kind is
        MISJUDGMENT_ADJUSTMENT and whose amount is new_awarded_points minus
        the old awarded_points - signed positive if the correction increased
        the credit, signed negative if it reduced it.'

        Original: weight=2, MANUAL, accuracy=1.0 -> mult=1.00, raw=20.
        Corrected: accuracy=0.5 -> mult=0.75, raw=15. delta = 15-20 = -5.
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
        correct_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            accuracy_score=0.5,
            reason="re-graded",
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

    def test_correct_updates_household_balance_by_delta(self, api):
        """PRD §3.4: 'It adjusts Household.points_balance and
        Household.lifetime_points_earned by the same signed delta.'"""
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
        hh_before = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh_before["points_balance"] == 20
        assert hh_before["lifetime_points_earned"] == 20
        correct_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            accuracy_score=0.5,
            reason="re-graded",
        )
        hh_after = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        # delta = -5
        assert hh_after["points_balance"] == 15
        assert hh_after["lifetime_points_earned"] == 15

    def test_correct_emits_audit_points_adjustment(self, api):
        """PRD §3.4: 'It appends an AuditLog entry of action POINTS_ADJUSTMENT
        and subject kind DISPOSAL.'"""
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
        correct_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            accuracy_score=0.5, reason="re-graded",
        )
        logs = list_audit_logs(
            scenario["community"]["id"],
            params={"action": "POINTS_ADJUSTMENT"},
        )
        matching = [
            log for log in logs
            if log.get("subject_kind") == "DISPOSAL"
            and log.get("subject_id") == d["id"]
        ]
        assert matching, "Expected POINTS_ADJUSTMENT audit entry for disposal"

    def test_correct_on_non_committed_disposal_rejected(self, api):
        """PRD §3.4: 'The correct capability operates only on disposals whose
        current status is COMMITTED.' Attempt on a CORRECTED disposal
        yields ERR_INVALID_STATE (PRD §2.10 priority 6)."""
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
        correct_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            accuracy_score=0.5, reason="first correction",
        )
        resp = api.correct_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            correct_disposal_payload(accuracy_score=0.3, reason="2nd attempt"),
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


class TestVoid:
    def test_void_committed_disposal_terminates_at_voided(self, api):
        """PRD §3.4: 'The disposal terminates at VOIDED.'"""
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
        voided = void_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            reason="duplicate entry",
        )
        assert voided["status"] == "VOIDED"

    def test_void_appends_misjudgment_adjustment_full_negative(self, api):
        """PRD §3.4: 'It appends a PointsTransaction whose kind is
        MISJUDGMENT_ADJUSTMENT and whose amount is the negative of the
        disposal's current awarded_points.'"""
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
        void_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            reason="dup",
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
        assert adj[0]["amount"] == -20

    def test_void_decreases_lifetime_by_awarded_points(self, api):
        """PRD §3.4: 'It decreases Household.points_balance and
        Household.lifetime_points_earned by awarded_points.'"""
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
        void_disposal(
            scenario["community"]["id"], scenario["household"]["id"], d["id"],
            reason="dup",
        )
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh["points_balance"] == 0
        assert hh["lifetime_points_earned"] == 0
