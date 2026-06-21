"""Keg-yield and reorder computed reads, par boundaries, keg-tap line overlap,
and the waste-log depletion cascade.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_product, create_keg_product, create_product_with_par,
    seed_on_hand_via_posted_invoice, create_keg_tap, get_product,
    keg_yield_params,
    INVENTORY_MANAGER, BAR_MANAGER,
)


def test_keg_yield_floor_nonlinear_with_explicit_loss(api):
    """PRD §3.2: "the system reports the theoretical serving count as the container volume
    divided by the pour size, dropped to the next lower whole number (`servings_theoretical`);
    the net serving count as the container volume multiplied by the quantity one minus the
    line-loss fraction, divided by the pour size, again dropped to the next lower whole number
    (`servings_net`); and the cost per serving as the product's `unit_cost_cents` divided by
    the net serving count, rounded half-up to a whole cent (`cost_per_serving_cents`)."

    Design: Difficulty/combinatorial_formula/keg_yield_floor_nonlinear_mode_a
    """
    keg = create_keg_product(sku="KEG-HB", name="House Lager", container_volume_ml=58670,
                             unit_cost_cents=15000)
    data = validate_success(api.keg_yield(keg["id"], BAR_MANAGER,
                                          params=keg_yield_params(473, 0.05)))
    assert data["servings_theoretical"] == 124
    assert data["servings_net"] == 117
    assert data["cost_per_serving_cents"] == 128


def test_keg_yield_default_line_loss_applied_when_omitted(api):
    """PRD §3.2: "A caller supplies a `pour_size_ml` and, optionally, a `line_loss_pct`
    that defaults to five hundredths (0.05, i.e. five percent of draft volume lost to line
    and foam)."

    Design: Corner/endpoints/keg_yield_default_line_loss_applied
    """
    keg = create_keg_product(sku="KEG-DL", name="Lager", container_volume_ml=58670,
                             unit_cost_cents=15000)
    data = validate_success(api.keg_yield(keg["id"], BAR_MANAGER,
                                          params=keg_yield_params(473)))
    assert data["servings_theoretical"] == 124
    assert data["servings_net"] == 117, "omitted line_loss_pct defaults to 0.05"


def test_keg_yield_on_bottle_rejected_not_a_keg(api):
    """PRD §3.2: "If the product's `container_type` is not `KEG`, the read is rejected
    with `ERR_NOT_A_KEG` (HTTP 422)."

    Design: Corner/validations/keg_yield_on_bottle_rejected_not_a_keg
    """
    bottle = create_product(sku="GIN-NK", name="Gin", container_type="BOTTLE",
                            container_volume_ml=750, unit_cost_cents=2000)
    validate_error(api.keg_yield(bottle["id"], BAR_MANAGER, params=keg_yield_params(44)),
                   ApiErrorId.ERR_NOT_A_KEG)


def test_reorder_suggestion_rounds_up_to_case_pack(api):
    """PRD §3.2: "When `on_hand_units` falls below the reorder point, `triggered` is true
    and the suggested quantity is computed in two steps — first take the difference between
    `par_level_units` and `on_hand_units` and round it up to the next whole container, then
    round that figure up to the nearest multiple of the product's `case_pack`."

    Design: Corner/calculations/reorder_suggestion_rounds_up_to_case_pack
    """
    product, _par = create_product_with_par(par_level_units=24, reorder_point_units=10,
                                             sku="VOD-RO", name="Vodka", unit_cost_cents=2200,
                                             case_pack=12)
    data = validate_success(api.reorder_suggestion(product["id"], INVENTORY_MANAGER))
    assert data["triggered"] is True, "on_hand 0 < reorder_point 10"
    assert data["suggested_qty"] == 24, "ceil(24-0)=24, already a multiple of case_pack 12"


def test_reorder_boundary_on_hand_equals_reorder_point_not_triggered(api):
    """PRD §3.2: "When `on_hand_units` is at least the active setting's
    `reorder_point_units`, no replenishment is needed: the response reports `triggered` as
    false and `suggested_qty` as 0."

    Design: Difficulty/boundary_precision_check/reorder_threshold_boundary_on_hand_equals_reorder_point
    """
    product, _par = create_product_with_par(par_level_units=24, reorder_point_units=10,
                                             sku="VOD-B6", name="Vodka", unit_cost_cents=2200,
                                             case_pack=12)
    # Seed on_hand to exactly the reorder_point (10) via a posted invoice.
    seed_on_hand_via_posted_invoice(product["id"], 10, unit_cost_cents=2200)
    assert get_product(product["id"])["on_hand_units"] == 10

    data = validate_success(api.reorder_suggestion(product["id"], INVENTORY_MANAGER))
    assert data["triggered"] is False, "on_hand == reorder_point (10) does NOT trigger (>= is satisfied)"
    assert data["suggested_qty"] == 0


def test_reorder_boundary_just_below_reorder_point_triggers(api):
    """PRD §2.8: "every product carries a computed boolean `needs_reorder` that is true
    exactly when `on_hand_units` is strictly less than the `reorder_point_units` of the
    product's currently active par setting, and false otherwise."
    PRD §3.2: "When `on_hand_units` is at least the active setting's `reorder_point_units`,
    no replenishment is needed: the response reports `triggered` as false and `suggested_qty`
    as 0. When `on_hand_units` falls below the reorder point, `triggered` is true."

    Design: Difficulty/boundary_precision_check/reorder_threshold_boundary_on_hand_equals_reorder_point
    """
    # X-1 boundary: on_hand 9 < reorder_point 10 triggers.
    product, _par = create_product_with_par(par_level_units=24, reorder_point_units=10,
                                             sku="VOD-B6L", name="Vodka", unit_cost_cents=2200,
                                             case_pack=12)
    seed_on_hand_via_posted_invoice(product["id"], 9, unit_cost_cents=2200)
    assert get_product(product["id"])["on_hand_units"] == 9
    data = validate_success(api.reorder_suggestion(product["id"], INVENTORY_MANAGER))
    assert data["triggered"] is True, "on_hand 9 < reorder_point 10 triggers replenishment"


def test_reorder_suggestion_without_active_par_rejected(api):
    """PRD §3.2: "The second computed read is the reorder suggestion, which requires the
    product to have an active par setting; if none exists, the read is rejected with
    `ERR_NO_ACTIVE_PAR` (HTTP 422)."

    Design: Corner/validations/reorder_suggestion_without_active_par_rejected
    """
    p = create_product(sku="P-NP", name="A", container_volume_ml=750, unit_cost_cents=100)
    validate_error(api.reorder_suggestion(p["id"], INVENTORY_MANAGER), ApiErrorId.ERR_NO_ACTIVE_PAR)


def test_invalid_par_reorder_point_above_par_rejected(api):
    """PRD §2.8: "A par setting names the `par_level_units` (the target full-stock level,
    which must be greater than zero) and the `reorder_point_units` (the replenishment
    trigger, which must be at least zero and at most the `par_level_units`). If those bounds
    are violated, the create is rejected with `ERR_INVALID_PAR` (HTTP 422)."

    Design: Corner/validations/invalid_par_reorder_point_above_par_rejected
    """
    p = create_product(sku="VOD-IP", name="Vodka", container_volume_ml=750, unit_cost_cents=2200)
    validate_error(api.create_par_setting({
        "product_id": p["id"], "par_level_units": 24, "reorder_point_units": 30}, INVENTORY_MANAGER),
        ApiErrorId.ERR_INVALID_PAR)


def test_keg_tap_overlapping_interval_rejected(api):
    """PRD §3.8: "Two taps on the same `draft_line_no` may not have overlapping closed
    intervals, but adjacency is allowed: a tap whose `tapped_from` exactly equals a previous
    tap's `tapped_until` is permitted, since kegs swap instantaneously. A tap whose interval
    genuinely overlaps an existing tap on the same line is rejected with `ERR_LINE_OVERLAP`
    (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/keg_tap_closed_interval_overlap_adjacency_allowed
    """
    keg = create_keg_product(sku="KEG-O8", name="Lager", container_volume_ml=58670,
                             unit_cost_cents=15000)
    create_keg_tap(keg["id"], 1, "2026-03-01T08:00:00Z", "2026-03-01T12:00:00Z")
    # 11:00-15:00 genuinely overlaps the 08:00-12:00 tap on line 1.
    validate_error(api.create_keg_tap({
        "product_id": keg["id"], "draft_line_no": 1,
        "tapped_from": "2026-03-01T11:00:00Z", "tapped_until": "2026-03-01T15:00:00Z"},
        BAR_MANAGER),
        ApiErrorId.ERR_LINE_OVERLAP)


def test_keg_tap_adjacent_interval_allowed(api):
    """PRD §3.8: "adjacency is allowed: a tap whose `tapped_from` exactly equals a previous
    tap's `tapped_until` is permitted, since kegs swap instantaneously."

    Design: Difficulty/resource_temporal_overlap/keg_tap_closed_interval_overlap_adjacency_allowed
    """
    keg = create_keg_product(sku="KEG-ADJ", name="Lager", container_volume_ml=58670,
                             unit_cost_cents=15000)
    create_keg_tap(keg["id"], 1, "2026-03-01T08:00:00Z", "2026-03-01T12:00:00Z")
    # Next tap starts exactly when the prior ended -> adjacency permitted.
    data = validate_success(api.create_keg_tap({
        "product_id": keg["id"], "draft_line_no": 1,
        "tapped_from": "2026-03-01T12:00:00Z", "tapped_until": "2026-03-01T16:00:00Z"},
        BAR_MANAGER), expected_status=201)
    assert data["draft_line_no"] == 1


def test_waste_log_cascades_onhand_then_reorder_flag(api):
    """PRD §3.8: "Recording waste also depletes stock: the product's `on_hand_units` is
    reduced by `wasted_units`, floored at zero so it never goes negative, and the affected
    product recomputes `needs_reorder`."
    PRD §3.8: "The event's `waste_cost_cents` is `wasted_units` multiplied by the product's
    `unit_cost_cents`, rounded half-up to a whole cent at log time."

    Design: Difficulty/transitive_cascade/waste_log_cascade_onhand_to_reorder_flag
    """
    product, _par = create_product_with_par(par_level_units=24, reorder_point_units=10,
                                             sku="WHIS-W", name="Whiskey", unit_cost_cents=3000,
                                             case_pack=1)
    # Seed on_hand to 11 so needs_reorder is false before the waste.
    seed_on_hand_via_posted_invoice(product["id"], 11, unit_cost_cents=3000)
    assert get_product(product["id"])["needs_reorder"] is False

    data = validate_success(api.create_waste_log({
        "product_id": product["id"], "reason": "BREAKAGE", "wasted_units": 2}, BAR_MANAGER),
        expected_status=201)
    assert data["waste_cost_cents"] == 6000, "2 * 3000"
    refreshed = get_product(product["id"])
    assert refreshed["on_hand_units"] == 9, "11 - 2 = 9"
    assert refreshed["needs_reorder"] is True, "9 < reorder_point 10 flips flag true"


def test_keg_yield_servings_net_below_theoretical_due_to_loss(api):
    """PRD §3.2: "the system reports the theoretical serving count as the container volume
    divided by the pour size, dropped to the next lower whole number (`servings_theoretical`);
    the net serving count as the container volume multiplied by the quantity one minus the
    line-loss fraction, divided by the pour size, again dropped to the next lower whole number
    (`servings_net`); and the cost per serving as the product's `unit_cost_cents` divided by
    the net serving count, rounded half-up to a whole cent (`cost_per_serving_cents`)."

    Design: Difficulty/combinatorial_formula/keg_yield_floor_nonlinear_mode_a
    """
    keg = create_keg_product(sku="KEG-HB2", name="House Lager", container_volume_ml=58670,
                             unit_cost_cents=15000)
    data = validate_success(api.keg_yield(keg["id"], BAR_MANAGER,
                                          params=keg_yield_params(473, 0.05)))
    # The 5% line loss makes the net serving count strictly lower than the theoretical count.
    assert data["servings_net"] < data["servings_theoretical"]
    assert data["servings_net"] == 117 and data["servings_theoretical"] == 124
    # cost_per_serving is computed against servings_net, not servings_theoretical.
    assert data["cost_per_serving_cents"] == 128
    assert data["cost_per_serving_cents"] != round(15000 / 124)


def test_waste_floors_on_hand_at_zero(api):
    """PRD §3.8: "Recording waste also depletes stock: the product's `on_hand_units` is
    reduced by `wasted_units`, floored at zero so it never goes negative, and the affected
    product recomputes `needs_reorder`."

    Design: Difficulty/transitive_cascade/waste_log_cascade_onhand_to_reorder_flag
    """
    product, _par = create_product_with_par(par_level_units=24, reorder_point_units=10,
                                             sku="WHIS-W2", name="Whiskey", unit_cost_cents=3000,
                                             case_pack=1)
    # on_hand seeded to 3; wasting 5 units floors on_hand at 0 (never negative).
    seed_on_hand_via_posted_invoice(product["id"], 3, unit_cost_cents=3000)
    validate_success(api.create_waste_log({
        "product_id": product["id"], "reason": "SPILL", "wasted_units": 5}, BAR_MANAGER),
        expected_status=201)
    refreshed = get_product(product["id"])
    assert refreshed["on_hand_units"] == 0, "depletion floored at 0, never negative"
    assert refreshed["needs_reorder"] is True, "0 < reorder_point 10"
