"""Redemption mall and order lifecycle.

Covers PRD §3.5: mall item creation, submit, confirm/reject, fulfill,
deliver, return, with stock and balance conservation.
"""
from __future__ import annotations

import pytest

from prd_bench_local_runner.testing import validate_error, validate_success
from test_helpers import (
    ApiErrorId,
    advance_clock,
    confirm_redemption,
    create_mall_item,
    deliver_redemption,
    fetch_household,
    fetch_redemption_order,
    fulfill_redemption,
    list_points_txns,
    make_community_admin_headers,
    make_resident_headers,
    return_redemption,
    return_redemption_order_payload,
    setup_scoring_scenario,
    setup_verified_resident,
    submit_disposal,
    submit_redemption,
    submit_redemption_order_payload,
)


def _scenario_with_balance(target_balance: int) -> dict:
    """Bootstrap a resident with `target_balance` points by submitting
    disposals against a generous-cap RECYCLABLE rule."""
    scenario = setup_scoring_scenario(
        base_rate_per_kg=10.00, daily_cap_points=10000,
        bonus_consecutive_threshold_days=365,
        peak_period_start_hour=0, peak_period_end_hour=0,
        rule_activated_at_iso="2030-01-01T00:00:00.000Z",
        advance_clock_to_iso="2030-01-01T01:00:00.000Z",
    )
    # Award target_balance via a single disposal (raw = base_rate * weight).
    weight = float(target_balance) / 10.0
    submit_disposal(
        scenario["community"], scenario["household"], scenario["resident"],
        disposal_time="2030-01-01T01:00:00.000Z",
        scoring_method="MANUAL", accuracy_score=1.0,
        weight_kg=round(weight, 3),
    )
    return scenario


class TestMallItemCreate:
    def test_create_mall_item_born_listed(self, api):
        """PRD §3.5: 'Items are born LISTED; the alternative status is
        DELISTED.'"""
        community, _, _ = setup_verified_resident()
        item = create_mall_item(community["id"], stock=5, cost_points=50)
        assert item["status"] == "LISTED"
        assert item["stock"] == 5
        assert item["cost_points"] == 50


class TestRedemptionSubmit:
    def test_submit_redemption_snapshots_unit_cost_and_channel(self, api):
        """PRD §3.5: 'On submit, the system snapshots the item's current
        cost_points onto the order as unit_cost_points and snapshots the
        item's current channel onto the order as channel.'"""
        scenario = _scenario_with_balance(200)
        item = create_mall_item(
            scenario["community"]["id"], stock=5, cost_points=50,
            channel="ONLINE",
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=2,
        )
        assert order["status"] == "SUBMITTED"
        assert order["unit_cost_points"] == 50
        assert order["channel"] == "ONLINE"
        assert order["total_cost_points"] == 100

    def test_submit_unlisted_item_yields_item_unavailable(self, api):
        """PRD §3.5: 'the target item is currently LISTED AND its
        community_id matches the path's community (else
        ERR_ITEM_UNAVAILABLE).'"""
        scenario = _scenario_with_balance(50)
        item = create_mall_item(
            scenario["community"]["id"], stock=5, cost_points=50,
        )
        # Delist.
        from test_helpers import patch_mall_item_payload
        api.patch_mall_item(
            scenario["community"]["id"], item["id"],
            patch_mall_item_payload(status="DELISTED"),
            make_community_admin_headers(),
        )
        resp = api.submit_redemption_order(
            scenario["community"]["id"],
            submit_redemption_order_payload(
                mall_item_id=item["id"],
                household_id=scenario["household"]["id"],
                resident_id=scenario["resident"]["id"],
                quantity=1,
            ),
            make_resident_headers(scenario["resident"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_ITEM_UNAVAILABLE.value)


class TestRedemptionConfirm:
    def test_confirm_decrements_stock_and_debits_balance(self, api):
        """PRD §3.5: 'on success it decrements MallItem.stock by quantity,
        appends a PointsTransaction whose kind is REDEMPTION_DEBIT and
        whose amount is the negative of total_cost_points, reduces
        Household.points_balance by total_cost_points.'"""
        scenario = _scenario_with_balance(200)
        item = create_mall_item(
            scenario["community"]["id"], stock=5, cost_points=50,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=2,
        )
        confirmed = confirm_redemption(
            scenario["community"]["id"], order["id"],
        )
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["confirmed_at"] is not None
        # Check stock and balance.
        from test_helpers import (
            api_client as ac,
            make_community_admin_headers as mh,
        )
        item_after = ac.list_mall_items(
            scenario["community"]["id"], mh(), params={"status": "LISTED"},
        ).json()["data"]
        match = [m for m in item_after if m["id"] == item["id"]]
        assert match and match[0]["stock"] == 3
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh["points_balance"] == 100  # 200 - 100

    def test_confirm_when_stock_below_quantity_yields_insufficient_stock(
        self, api,
    ):
        """PRD §3.5: 'Confirm requires SUBMITTED AND MallItem.stock at or
        above the order's quantity (else ERR_INSUFFICIENT_STOCK).'"""
        scenario = _scenario_with_balance(200)
        item = create_mall_item(
            scenario["community"]["id"], stock=1, cost_points=50,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=2,
        )
        resp = api.confirm_redemption_order(
            scenario["community"]["id"], order["id"],
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_STOCK.value)

    def test_confirm_when_balance_below_cost_yields_insufficient_points(
        self, api,
    ):
        """PRD §3.5: 'Confirm requires ... AND Household.points_balance at
        or above total_cost_points (else ERR_INSUFFICIENT_POINTS).'

        Balance=50, cost=100, stock OK -> only fiscal check fails.
        """
        scenario = _scenario_with_balance(50)
        item = create_mall_item(
            scenario["community"]["id"], stock=10, cost_points=100,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=1,
        )
        resp = api.confirm_redemption_order(
            scenario["community"]["id"], order["id"],
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_POINTS.value)


class TestRedemptionFulfillDeliverReturn:
    def test_full_lifecycle_to_delivered(self, api):
        """PRD §3.5: 'Confirmed orders progress through fulfillment by admin
        action: fulfill ... deliver (requires FULFILLED, sets delivered_at
        ... transitions to DELIVERED which is terminal).'"""
        scenario = _scenario_with_balance(200)
        item = create_mall_item(
            scenario["community"]["id"], stock=5, cost_points=50,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=1,
        )
        confirm_redemption(scenario["community"]["id"], order["id"])
        fulfilled = fulfill_redemption(scenario["community"]["id"], order["id"])
        assert fulfilled["status"] == "FULFILLED"
        delivered = deliver_redemption(scenario["community"]["id"], order["id"])
        assert delivered["status"] == "DELIVERED"
        assert delivered["delivered_at"] is not None

    def test_return_recredits_stock_and_balance(self, api):
        """PRD §3.5: 'A return capability operates only on FULFILLED orders,
        requires a non-empty reason, re-credits stock by adding quantity
        back to the item, appends a PointsTransaction whose kind is
        REDEMPTION_REFUND and whose amount is the positive total_cost_points,
        and restores Household.points_balance by the same amount.'"""
        scenario = _scenario_with_balance(200)
        item = create_mall_item(
            scenario["community"]["id"], stock=5, cost_points=50,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=2,
        )
        confirm_redemption(scenario["community"]["id"], order["id"])
        fulfill_redemption(scenario["community"]["id"], order["id"])
        returned = return_redemption(
            scenario["community"]["id"], order["id"],
            reason="Item damaged",
        )
        assert returned["status"] == "RETURNED"
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        # Initially 200, debit 100 at confirm, refund 100 at return -> 200.
        assert hh["points_balance"] == 200
        # Refund txn exists.
        txns = list_points_txns(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        refund = [t for t in txns if t["kind"] == "REDEMPTION_REFUND"]
        assert len(refund) == 1
        assert refund[0]["amount"] == 100

    def test_action_on_terminal_order_rejected_as_delivery_terminal(
        self, api,
    ):
        """PRD §3.5: 'Attempts to invoke any redemption transition on an
        order already in a terminal state (DELIVERED, REJECTED, or RETURNED)
        are rejected with ERR_DELIVERY_TERMINAL.'"""
        scenario = _scenario_with_balance(200)
        item = create_mall_item(
            scenario["community"]["id"], stock=5, cost_points=50,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=1,
        )
        confirm_redemption(scenario["community"]["id"], order["id"])
        fulfill_redemption(scenario["community"]["id"], order["id"])
        deliver_redemption(scenario["community"]["id"], order["id"])
        # Now attempt to return the DELIVERED order.
        resp = api.return_redemption_order(
            scenario["community"]["id"], order["id"],
            return_redemption_order_payload("late attempt"),
            make_community_admin_headers(),
        )
        validate_error(resp, ApiErrorId.ERR_DELIVERY_TERMINAL.value)


class TestRedemptionReject:
    def test_reject_submitted_order_no_stock_or_points_movement(self, api):
        """PRD §3.5: 'Reject requires the order is currently SUBMITTED and
        performs no stock or points movement; it transitions to REJECTED
        (terminal).'"""
        from test_helpers import reject_redemption_order_payload
        scenario = _scenario_with_balance(200)
        item = create_mall_item(
            scenario["community"]["id"], stock=5, cost_points=50,
        )
        order = submit_redemption(
            scenario["community"], scenario["household"], scenario["resident"],
            item, quantity=2,
        )
        resp = api.reject_redemption_order(
            scenario["community"]["id"], order["id"],
            reject_redemption_order_payload("no justification"),
            make_community_admin_headers(),
        )
        data = validate_success(resp)
        assert data["status"] == "REJECTED"
        hh = fetch_household(
            scenario["community"]["id"], scenario["household"]["id"],
        )
        assert hh["points_balance"] == 200  # untouched
