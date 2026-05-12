"""Concurrency races where the PRD explicitly defines the outcome.

The PRD names specific outcomes for several races; only those are tested.
Where the PRD names a loser error_id, we still use validate_error_is_one_of
to accept either the named loser code or a generic state-check fall-through
to avoid scaffold-leakage (PRD precedence is not over-pinned).
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import (
    assert_exactly_one_succeeds,
    run_race,
    validate_error_is_one_of,
    validate_success,
)
from test_helpers import (
    ApiErrorId,
    advance_clock,
    create_mall_item,
    fetch_household,
    make_community_admin_headers,
    setup_scoring_scenario,
    setup_verified_resident,
    submit_disposal,
    submit_redemption,
)
from test_helpers import api_client as api_singleton


class TestConcurrencyRedemptionConfirm:
    def test_two_confirms_on_same_order_exactly_one_succeeds(self, api):
        """PRD §3.5: 'Two simultaneous confirms on the same order serialize
        first-writer-wins on RedemptionOrder.status; the loser receives
        ERR_INVALID_STATE.'"""
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
        item = create_mall_item(
            scenario["community"]["id"], stock=10, cost_points=50,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=1,
        )
        admin_headers = make_community_admin_headers()
        comm_id = scenario["community"]["id"]
        oid = order["id"]
        results = run_race(
            lambda: api.confirm_redemption_order(comm_id, oid, admin_headers),
            lambda: api.confirm_redemption_order(comm_id, oid, admin_headers),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        # PRD names ERR_INVALID_STATE as the loser code.
        loser = outcome["failures"][0]
        validate_error_is_one_of(loser, [ApiErrorId.ERR_INVALID_STATE.value])

    def test_two_confirms_on_last_stock_unit_one_fails_for_stock(self, api):
        """PRD §3.5: 'Two confirms competing for the last available stock
        unit serialize first-writer-wins on the stock decrement; orders
        that would drive MallItem.stock below zero are rejected as
        ERR_INSUFFICIENT_STOCK.'"""
        scenario = setup_scoring_scenario(
            base_rate_per_kg=10.00, daily_cap_points=10000,
            bonus_consecutive_threshold_days=365,
            peak_period_start_hour=0, peak_period_end_hour=0,
            rule_activated_at_iso="2030-01-01T00:00:00.000Z",
            advance_clock_to_iso="2030-01-01T01:00:00.000Z",
        )
        # Two residents in the same community with enough points each.
        from test_helpers import (
            create_household, create_resident, verify_resident,
        )
        hh2 = create_household(scenario["community"]["id"])
        r2 = create_resident(scenario["community"]["id"], hh2["id"])
        verify_resident(scenario["community"]["id"], hh2["id"], r2["id"])
        # Give each enough points.
        submit_disposal(
            scenario["community"], scenario["household"], scenario["resident"],
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=10.0,
        )
        submit_disposal(
            scenario["community"], hh2, r2,
            disposal_time="2030-01-01T01:00:00.000Z",
            scoring_method="MANUAL", accuracy_score=1.0, weight_kg=10.0,
        )
        # Item with stock=1.
        item = create_mall_item(
            scenario["community"]["id"], stock=1, cost_points=50,
        )
        order_a = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=1,
        )
        order_b = submit_redemption(
            scenario["community"], hh2, r2, item, quantity=1,
        )
        comm_id = scenario["community"]["id"]
        admin = make_community_admin_headers()
        results = run_race(
            lambda: api.confirm_redemption_order(comm_id, order_a["id"], admin),
            lambda: api.confirm_redemption_order(comm_id, order_b["id"], admin),
        )
        outcome = assert_exactly_one_succeeds(results[0], results[1])
        loser = outcome["failures"][0]
        # PRD names ERR_INSUFFICIENT_STOCK as the loser code.
        validate_error_is_one_of(loser, [ApiErrorId.ERR_INSUFFICIENT_STOCK.value])
