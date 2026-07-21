"""Fusti freshness: best-by computation, low-on-creation, label-vs-sensory decay variants."""
import pytest
from test_helpers import (
    validate_success, ApiErrorId, assert_same_instant,
    create_member, create_bulk_product, create_fusti, create_order, pay_order, fulfill_order,
    set_clock, refill_line, TEST_USERS,
)

INV = TEST_USERS["inventory_manager_headers"]


# ── Corner: entities / fusti_best_by_date_computed_from_harvest ──

def test_fusti_best_by_computed_from_harvest_plus_shelf_life(api):
    """PRD §3.2: "its `best_by_date` is computed as the harvest date plus the product's
    `shelf_life_days`". PRD §3.2: "The vessel also reports `is_past_best_by`, which is true
    exactly when the logical now is at or after the best-by date."

    Design: Corner/entities/fusti_best_by_date_computed_from_harvest
    """
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    fusti = create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                         reorder_point_ml=2000, harvest_date="2026-01-01T00:00:00Z")
    assert_same_instant(fusti["best_by_date"], "2027-06-25T00:00:00Z")
    assert fusti["is_past_best_by"] is False
    assert fusti["status"] == "IN_SERVICE"


# ── Corner: entities / fusti_created_below_reorder_starts_low ──

def test_fusti_created_at_or_below_reorder_opens_low(api):
    """PRD §3.2: "A fresh vessel opens in `IN_SERVICE` posture, except that if its initial
    volume is at or below the reorder point it opens directly in `LOW`."

    Design: Corner/entities/fusti_created_below_reorder_starts_low
    """
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    fusti = create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=1500,
                         reorder_point_ml=2000, harvest_date="2026-06-01T00:00:00Z")
    assert fusti["status"] == "LOW", f"expected LOW (1500 <= 2000), got {fusti['status']}"


# ── Corner: calculations / fusti_freshness_unopened_sensory_equals_label ──

def test_unopened_fusti_sensory_equals_label(api):
    """PRD §3.2: "The `sensory_freshness_score` equals the label score for as long as
    `first_draw_at` is null."

    Design: Corner/calculations/fusti_freshness_unopened_sensory_equals_label
    """
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    fusti = create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                         reorder_point_ml=2000, harvest_date="2026-06-01T00:00:00Z")
    fresh = validate_success(api.get_fusti(fusti["id"], INV))
    assert fresh["label_freshness_score"] == 94.44, fresh["label_freshness_score"]
    assert fresh["sensory_freshness_score"] == 94.44, fresh["sensory_freshness_score"]


# ── Difficulty: dual_variant_calc / fusti_freshness_label_vs_sensory ──

def _open_fusti_at_april_read_may(api):
    """Open a 2026-01-01/540d fusti via a fulfilled 100ml draw at 2026-04-01, read at 2026-05-01."""
    set_clock(api, "2026-04-01T00:00:00Z")
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    fusti = create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                         reorder_point_ml=1000, harvest_date="2026-01-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 100)])
    order = pay_order(api, member, order)
    fulfill_order(api, order)
    set_clock(api, "2026-05-01T00:00:00Z")
    return validate_success(api.get_fusti(fusti["id"], INV))


def test_label_score_is_forward_looking_interpolation(api):
    """PRD §3.2: "The `label_freshness_score` is one hundred multiplied by one minus the ratio
    of that elapsed age to the product's shelf life in days, floored at zero and rounded half up
    to two decimal places — a straight, forward-looking interpolation toward the best-by date."

    Design: Difficulty/dual_variant_calc/fusti_freshness_label_vs_sensory
    """
    fresh = _open_fusti_at_april_read_may(api)
    assert fresh["label_freshness_score"] == 77.78, fresh["label_freshness_score"]


def test_sensory_score_decays_from_open_event_below_label(api):
    """PRD §3.2: "the sensory score instead decays chronologically from the moment of opening:
    compute the label-style score using the elapsed age measured at `first_draw_at` (the opening
    age, again as one hundred times one minus opening-age-over-shelf-life, floored at zero), then
    subtract 2.5 points for every day elapsed between `first_draw_at` and the logical now, floor
    the result at zero, and round half up to two decimal places."

    Design: Difficulty/dual_variant_calc/fusti_freshness_label_vs_sensory
    """
    fresh = _open_fusti_at_april_read_may(api)
    assert fresh["sensory_freshness_score"] == 8.33, fresh["sensory_freshness_score"]
    assert fresh["sensory_freshness_score"] < fresh["label_freshness_score"]
