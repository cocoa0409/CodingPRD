"""Shoe rotation: cumulative mileage rollup and the REORDER_DUE threshold, plus the
SHOE-category guard for shoe-pair creation."""
from test_helpers import (
    validate_error, ApiErrorId,
    make_member_headers,
    fixtures as fx,
)
import test_helpers.factories as f


def _shoe_pair(api, max_mileage_km=500):
    member = fx.new_member(api)
    product = fx.new_product(api, category="SHOE", name="Trainer", price_cents=15000,
                             stock_on_hand=10, max_mileage_km=max_mileage_km)
    pair = fx.new_shoe_pair(api, member["id"], product["id"])
    return member, product, pair


def test_mileage_reaching_threshold_exactly_triggers_reorder(api):
    """PRD §3.8: "A mileage reminder fires when the accumulated distance reaches the
    threshold: while the pair is `ACTIVE`, if the recomputed `total_mileage_km` is
    greater than or equal to `reminder_threshold_km`, the pair transitions to
    `REORDER_DUE` (exactly reaching the threshold triggers it)."

    Design: Difficulty/boundary_precision_check/shoe_mileage_reaches_threshold_exactly_triggers_reorder
    """
    member, product, pair = _shoe_pair(api, max_mileage_km=500)
    fx.log_run(api, pair["id"], member["id"], 300)
    updated = fx.log_run(api, pair["id"], member["id"], 200)  # total 500 == threshold
    assert updated["total_mileage_km"] == 500
    assert updated["status"] == "REORDER_DUE"


def test_mileage_above_threshold_triggers_reorder(api):
    """PRD §3.8: "while the pair is `ACTIVE`, if the recomputed `total_mileage_km` is
    greater than or equal to `reminder_threshold_km`, the pair transitions to
    `REORDER_DUE` (exactly reaching the threshold triggers it)."

    Design: Difficulty/boundary_precision_check/shoe_mileage_reaches_threshold_exactly_triggers_reorder
    """
    member, product, pair = _shoe_pair(api, max_mileage_km=500)
    fx.log_run(api, pair["id"], member["id"], 300)
    updated = fx.log_run(api, pair["id"], member["id"], 201)  # total 501 > threshold
    assert updated["total_mileage_km"] == 501
    assert updated["status"] == "REORDER_DUE"


def test_mileage_below_threshold_keeps_active(api):
    """PRD §3.8: "while the pair is `ACTIVE`, if the recomputed `total_mileage_km` is
    greater than or equal to `reminder_threshold_km`, the pair transitions to
    `REORDER_DUE` (exactly reaching the threshold triggers it)."

    Design: Corner/state_machines/run_log_below_threshold_keeps_shoepair_active
    """
    member, product, pair = _shoe_pair(api, max_mileage_km=500)
    fx.log_run(api, pair["id"], member["id"], 300)
    updated = fx.log_run(api, pair["id"], member["id"], 199)  # total 499 < threshold
    assert updated["total_mileage_km"] == 499
    assert updated["status"] == "ACTIVE"


def test_shoe_pair_on_non_shoe_product_rejected(api):
    """PRD §3.8: "The referenced product must be of `category` `SHOE`; registering
    against any other category is rejected with `ERR_PRODUCT_NOT_SHOE` (422)."

    Design: Corner/validations/shoepair_create_on_non_shoe_product_returns_error
    """
    member = fx.new_member(api)
    product = fx.new_product(api, category="GEAR", name="Gel", price_cents=500, stock_on_hand=5)
    resp = api.create_shoe_pair(f.create_shoe_pair_payload(member["id"], product["id"]), make_member_headers(member["id"]))
    validate_error(resp, ApiErrorId.ERR_PRODUCT_NOT_SHOE, 422)
