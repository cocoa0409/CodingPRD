"""Disposal creation validation: precedence, weight/volume exclusivity,
time bounds, resident-inactive guards, and absence-of-rule guard.

Covers PRD §3.3 and §2.10.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_community,
    create_disposal_payload,
    create_household,
    create_resident,
    make_community_admin_headers,
    make_resident_headers,
    setup_active_point_rule,
    setup_scoring_scenario,
    setup_verified_resident,
)


class TestDisposalCreationGuards:
    def test_resident_inactive_pending_yields_resident_inactive(self, api):
        """PRD §3.3: 'the resident must also have identity_status of
        VERIFIED AND account_status of ACTIVE.' PRD §2.10: 'resident-active
        check (ERR_RESIDENT_INACTIVE).'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community = create_community()
        household = create_household(community["id"])
        resident = create_resident(community["id"], household["id"])
        # Activate a rule so absence-of-rule doesn't fire first.
        setup_active_point_rule(community["id"], "2030-01-01T00:00:00.000Z")
        payload = create_disposal_payload(
            resident_id=resident["id"],
            disposal_time="2030-01-01T00:00:00.000Z",
        )
        resp = api.create_disposal(
            community["id"], household["id"], payload,
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESIDENT_INACTIVE.value)

    def test_no_active_rule_yields_no_active_rule(self, api):
        """PRD §3.3: 'the absence of such a rule yields ERR_NO_ACTIVE_RULE.'"""
        advance_clock("2030-01-01T00:00:00.000Z")
        community, household, resident = setup_verified_resident()
        # No PointRule created/activated.
        payload = create_disposal_payload(
            resident_id=resident["id"],
            disposal_time="2030-01-01T00:00:00.000Z",
        )
        resp = api.create_disposal(
            community["id"], household["id"], payload,
            make_resident_headers(resident["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_RULE.value)

    def test_neither_weight_nor_volume_yields_exclusivity(self, api):
        """PRD §3.3: 'Exactly one of weight_kg and volume_liters must be
        supplied - both null or both set is rejected with
        ERR_WEIGHT_VOLUME_EXCLUSIVITY.'"""
        scenario = setup_scoring_scenario(
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        payload = create_disposal_payload(
            resident_id=scenario["resident"]["id"],
            disposal_time="2030-01-01T01:00:00.000Z",
        )
        payload.pop("weight_kg", None)
        payload["weight_kg"] = None
        payload["volume_liters"] = None
        resp = api.create_disposal(
            scenario["community"]["id"], scenario["household"]["id"], payload,
            make_resident_headers(scenario["resident"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WEIGHT_VOLUME_EXCLUSIVITY.value)

    def test_both_weight_and_volume_yields_exclusivity(self, api):
        """PRD §3.3: 'Exactly one of weight_kg and volume_liters must be
        supplied - both null or both set is rejected with
        ERR_WEIGHT_VOLUME_EXCLUSIVITY.'"""
        scenario = setup_scoring_scenario(
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        payload = create_disposal_payload(
            resident_id=scenario["resident"]["id"],
            disposal_time="2030-01-01T01:00:00.000Z",
            weight_kg=2.0,
            volume_liters=5.0,
        )
        resp = api.create_disposal(
            scenario["community"]["id"], scenario["household"]["id"], payload,
            make_resident_headers(scenario["resident"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_WEIGHT_VOLUME_EXCLUSIVITY.value)

    def test_disposal_time_in_future_rejected(self, api):
        """PRD §3.3: 'the disposal_time ... which must be at or before the
        current logical clock and no earlier than 24 hours before it, with
        violations of either bound rejected as ERR_DISPOSAL_TIME_INVALID.'"""
        scenario = setup_scoring_scenario(
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        payload = create_disposal_payload(
            resident_id=scenario["resident"]["id"],
            disposal_time="2030-01-01T02:00:00.000Z",  # future
        )
        resp = api.create_disposal(
            scenario["community"]["id"], scenario["household"]["id"], payload,
            make_resident_headers(scenario["resident"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPOSAL_TIME_INVALID.value)

    def test_disposal_time_more_than_24h_before_now_rejected(self, api):
        """PRD §3.3: 'no earlier than 24 hours before it ... rejected as
        ERR_DISPOSAL_TIME_INVALID.'"""
        scenario = setup_scoring_scenario(
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-03T00:00:00.000Z",
        )
        # disposal_time is 48h before clock.
        payload = create_disposal_payload(
            resident_id=scenario["resident"]["id"],
            disposal_time="2030-01-01T00:00:00.000Z",
        )
        resp = api.create_disposal(
            scenario["community"]["id"], scenario["household"]["id"], payload,
            make_resident_headers(scenario["resident"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_DISPOSAL_TIME_INVALID.value)


class TestDisposalCommitSuccess:
    def test_disposal_commit_sets_status_committed_and_credits(self, api):
        """PRD §3.3: 'The disposal transitions from PENDING to COMMITTED.'
        PRD §3.3: 'update Household.points_balance and ...
        lifetime_points_earned upward by awarded_points.'"""
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            category_bonus_flat=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        payload = create_disposal_payload(
            resident_id=scenario["resident"]["id"],
            disposal_time="2030-01-01T01:00:00.000Z",
            weight_kg=2.0, scoring_method="MANUAL", accuracy_score=1.000,
        )
        resp = api.create_disposal(
            scenario["community"]["id"], scenario["household"]["id"], payload,
            make_resident_headers(scenario["resident"]["id"]),
        )
        data = validate_success(resp, expected_status=201)
        assert data["status"] == "COMMITTED"
        # raw = 10 * 2.0 * 1.00 = 20 (MANUAL multiplier = 0.50 + 0.50*1.0 = 1.00)
        assert data["awarded_points"] == 20
        assert data["cap_overflow_points"] == 0
        assert data["applied_rule_id"] == scenario["rule"]["id"]
