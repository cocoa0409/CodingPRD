"""Stem substitution policy enforcement.

Translates queue-B Corner calculations instances covering substitution_policy
(SAME_VALUE positive delta, NONE any swap, FLORIST_CHOICE over cap).
"""
import pytest
from test_helpers import (
    api_client, validate_error,
    make_florist_headers,
    setup_accepted_order, TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


def test_same_value_positive_delta_substitution_rejected(api):
    """PRD §3.5: "Under `SAME_VALUE`, a swap with a positive `price_delta_cents` is
    rejected (only equal-or-lower-priced swaps are permitted)."
    PRD §3.5: "Any swap that violates the policy is rejected with
    `ERR_SUBSTITUTION_NOT_ALLOWED`."

    Design: Corner/calculations/same_value_substitution_positive_delta_rejected
    """
    ctx, order, _wf = setup_accepted_order(
        "2027-01-05T08:00:00Z",
        zone_overrides={"zone_code": "ZK1", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CK1", "display_name": "CK1", "base_price_cents": 5000,
                               "substitution_policy": "SAME_VALUE"},
        florist_overrides={"shop_name": "ShopK1", "daily_capacity": 5},
        order_overrides={"delivery_date": "2027-01-10", "window_start_minute": 540,
                         "window_end_minute": 720})
    res = api.create_substitution(
        {"order_id": order["id"], "florist_id": ctx["florist"]["id"], "removed_stem": "rose",
         "added_stem": "orchid", "price_delta_cents": 100},
        make_florist_headers(ctx["florist"]["id"]))
    validate_error(res, "ERR_SUBSTITUTION_NOT_ALLOWED", expected_status=409)


def test_none_policy_rejects_any_substitution(api):
    """PRD §3.5: "Under `NONE`, any swap is rejected."
    PRD §3.5: "Any swap that violates the policy is rejected with
    `ERR_SUBSTITUTION_NOT_ALLOWED`."

    Design: Corner/calculations/none_policy_rejects_any_substitution
    """
    ctx, order, _wf = setup_accepted_order(
        "2027-01-15T08:00:00Z",
        zone_overrides={"zone_code": "ZK2", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CK2", "display_name": "CK2", "base_price_cents": 5000,
                               "substitution_policy": "NONE"},
        florist_overrides={"shop_name": "ShopK2", "daily_capacity": 5},
        order_overrides={"delivery_date": "2027-01-20", "window_start_minute": 540,
                         "window_end_minute": 720})
    # Even a zero-delta swap is rejected under NONE.
    res = api.create_substitution(
        {"order_id": order["id"], "florist_id": ctx["florist"]["id"], "removed_stem": "rose",
         "added_stem": "lily", "price_delta_cents": 0},
        make_florist_headers(ctx["florist"]["id"]))
    validate_error(res, "ERR_SUBSTITUTION_NOT_ALLOWED", expected_status=409)


def test_florist_choice_over_cap_substitution_rejected(api):
    """PRD §3.5: "Under `FLORIST_CHOICE`, a swap is rejected when the sum of the
    accepted substitution deltas for the order would rise above the cap, where the
    cap is the arrangement's `base_price_cents` multiplied by its
    `substitution_cap_pct`, rounded half-up to a whole cent."

    Design: Corner/calculations/florist_choice_over_cap_rejected
    """
    ctx, order, _wf = setup_accepted_order(
        "2027-03-01T08:00:00Z",
        zone_overrides={"zone_code": "ZK4", "base_delivery_fee_cents": 800,
                        "same_day_cutoff_hour_utc": 14, "window_capacity_per_slot": 5},
        arrangement_overrides={"sku": "CK4", "display_name": "CK4", "base_price_cents": 10000,
                               "substitution_policy": "FLORIST_CHOICE", "substitution_cap_pct": 0.15},
        florist_overrides={"shop_name": "ShopK4", "daily_capacity": 5},
        order_overrides={"delivery_date": "2027-03-05", "window_start_minute": 540,
                         "window_end_minute": 720})
    # cap = 10000 * 0.15 = 1500; delta 1600 exceeds the cap.
    res = api.create_substitution(
        {"order_id": order["id"], "florist_id": ctx["florist"]["id"], "removed_stem": "rose",
         "added_stem": "protea", "price_delta_cents": 1600},
        make_florist_headers(ctx["florist"]["id"]))
    validate_error(res, "ERR_SUBSTITUTION_NOT_ALLOWED", expected_status=409)
