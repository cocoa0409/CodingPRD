"""Cascade depth, conservation invariants, and the freshness eligibility boundary.

Covers queue A transitive_cascade (complete-roast and cancel-order chains),
compensating_invariant (green and roasted conservation),
combinatorial_formula/freshness_eligibility_nested_min_three_inputs, and queue B
green_lot_computed_inventory_on_create.
"""
import pytest
from test_helpers import (
    validate_success, validate_error, get_success_data,
    setup_catalog, produce_roasted_lot, create_green_lot, create_planned_batch,
    place_order, reserve_fulfillment, clock_set,
    start_roast_batch_payload, complete_roast_batch_payload,
    order_line, create_fulfillment_payload,
    TEST_USERS,
)

ROASTER = TEST_USERS["roaster_headers"]
SALES = TEST_USERS["sales_headers"]


# ─── transitive_cascade / complete_roast_cascade_green_then_roastedlot_creation ─

def test_start_drops_green_below_par_cascade(api):
    """PRD §3.3: "On a successful start the batch's `actual_green_kg` is recorded, the green
    lot's reservation of `planned_green_kg` is dropped (the batch has left `PLANNED`) while
    its consumption rises by `actual_green_kg`, the green lot's `on_hand_kg`, `reserved_kg`,
    `available_kg`, and `reorder_status` are recomputed".
    PRD §2.7: "The lot's `reorder_status` is `BELOW_PAR` when `available_kg` is strictly less
    than `par_level_kg`, and `OK` otherwise".

    Design: Difficulty/transitive_cascade/complete_roast_cascade_green_then_roastedlot_creation
    """
    product = setup_catalog()["product"]
    gl = create_green_lot(received_kg=30, par_level_kg=25)
    batch = create_planned_batch(gl["id"], product["id"], planned_green_kg=28)
    api.start_roast_batch(batch["id"], start_roast_batch_payload(28), ROASTER)
    gl_read = validate_success(api.get_green_lot(gl["id"], ROASTER), 200)
    assert gl_read["available_kg"] == 2.000, \
        f"available_kg should be 2.000 (30 - 28 consumed), got {gl_read['available_kg']}"
    assert gl_read["reorder_status"] == "BELOW_PAR", \
        f"2.000 < par 25 -> BELOW_PAR, got {gl_read['reorder_status']}"


def test_complete_cascade_creates_roasted_lot_with_availability(api):
    """PRD §3.3: "Completion also cascades a child **roasted lot** into existence, copying
    the producing batch's `roast_batch_id`, the `product_id`, the `roast_date`, and a
    `produced_kg` equal to the batch's `actual_roasted_kg`."
    PRD §2.8: "Its `available_kg` is `produced_kg` minus `reserved_kg`, rounded half-up to
    three decimals and clamped at zero."

    Design: Difficulty/transitive_cascade/complete_roast_cascade_green_then_roastedlot_creation
    """
    product = setup_catalog()["product"]
    gl = create_green_lot(received_kg=30, par_level_kg=25)
    _, lot = produce_roasted_lot(product["id"], green_lot_id=gl["id"],
                                 actual_green_kg=28, actual_roasted_kg=24, planned_green_kg=28)
    assert lot["produced_kg"] == 24.000, \
        f"produced_kg should equal actual_roasted_kg 24.000, got {lot['produced_kg']}"
    assert lot["available_kg"] == 24.000, \
        f"fresh lot available_kg should be 24.000, got {lot['available_kg']}"


# ─── transitive_cascade / cancel_order_cascade_fulfillment_releases_roastedlot ─

def test_cancel_order_cascades_fulfillment_cancellation(api):
    """PRD §3.4: "Cancelling an order also cancels every `RESERVED` fulfillment on it, and
    each such cancellation releases that fulfillment's roasted-lot reservation so the roasted
    lot's `reserved_kg` and `available_kg` recompute".

    Design: Difficulty/transitive_cascade/cancel_order_cascade_fulfillment_releases_roastedlot
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 8)])
    ful = reserve_fulfillment(order["id"], prod["id"], lot["id"], 8)
    cancelled = validate_success(api.cancel_order(order["id"], SALES), 200)
    assert cancelled["fulfillment_status"] == "CANCELLED"
    ful_read = validate_success(api.get_fulfillment(ful["id"], SALES), 200)
    assert ful_read["status"] == "CANCELLED", \
        f"cascade must cancel the RESERVED fulfillment, got {ful_read['status']}"


def test_cancel_order_releases_roasted_lot_reservation(api):
    """PRD §3.4: "each such cancellation releases that fulfillment's roasted-lot reservation
    so the roasted lot's `reserved_kg` and `available_kg` recompute".
    PRD §2.8: "Its `available_kg` is `produced_kg` minus `reserved_kg`, rounded half-up to
    three decimals and clamped at zero."

    Design: Difficulty/transitive_cascade/cancel_order_cascade_fulfillment_releases_roastedlot
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 8)])
    reserve_fulfillment(order["id"], prod["id"], lot["id"], 8)
    api.cancel_order(order["id"], SALES)
    lot_read = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    assert lot_read["available_kg"] == 25.000, \
        f"reservation released -> available restored to 25.000, got {lot_read['available_kg']}"


# ─── compensating_invariant / cancel_batch_conserves_green_kg ───────────────

def test_cancel_planned_batch_releases_green_reservation(api):
    """PRD §3.3: "Cancellation releases the batch's `planned_green_kg` reservation and
    recomputes the green lot's `reserved_kg`, `available_kg`, and `reorder_status`".

    Design: Difficulty/compensating_invariant/cancel_batch_conserves_green_kg
    """
    product = setup_catalog()["product"]
    gl = create_green_lot(received_kg=40, par_level_kg=5)
    batch = create_planned_batch(gl["id"], product["id"], planned_green_kg=20)
    api.cancel_roast_batch(batch["id"], ROASTER)
    gl_read = validate_success(api.get_green_lot(gl["id"], ROASTER), 200)
    assert gl_read["reserved_kg"] == 0.000, \
        f"reservation released -> reserved_kg 0.000, got {gl_read['reserved_kg']}"


def test_cancel_planned_batch_restores_available_no_drift(api):
    """PRD §2.7: "The `available_kg` is `on_hand_kg` minus `reserved_kg`, rounded half-up to
    three decimals and clamped at zero."
    PRD §3.3: "Cancellation releases the batch's `planned_green_kg` reservation and recomputes
    the green lot's `reserved_kg`, `available_kg`, and `reorder_status`".

    Design: Difficulty/compensating_invariant/cancel_batch_conserves_green_kg
    """
    product = setup_catalog()["product"]
    gl = create_green_lot(received_kg=40, par_level_kg=5)
    batch = create_planned_batch(gl["id"], product["id"], planned_green_kg=20)
    api.cancel_roast_batch(batch["id"], ROASTER)
    gl_read = validate_success(api.get_green_lot(gl["id"], ROASTER), 200)
    assert gl_read["available_kg"] == 40.000, \
        f"available_kg must return to received_kg 40.000 with zero drift, got {gl_read['available_kg']}"


# ─── compensating_invariant / cancel_fulfillment_conserves_roasted_kg ───────

def test_cancel_fulfillment_releases_roasted_reservation(api):
    """PRD §3.5: "Cancellation releases the roasted-lot reservation so the lot's
    `reserved_kg` and `available_kg` recompute".

    Design: Difficulty/compensating_invariant/cancel_fulfillment_conserves_roasted_kg
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 8)])
    ful = reserve_fulfillment(order["id"], prod["id"], lot["id"], 8)
    api.cancel_fulfillment(ful["id"], SALES)
    lot_read = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    assert lot_read["reserved_kg"] == 0.000, \
        f"reservation released -> reserved_kg 0.000, got {lot_read['reserved_kg']}"


def test_cancel_fulfillment_restores_available_no_drift(api):
    """PRD §2.8: "Its `available_kg` is `produced_kg` minus `reserved_kg`, rounded half-up to
    three decimals and clamped at zero."
    PRD §3.5: "Cancellation releases the roasted-lot reservation so the lot's `reserved_kg`
    and `available_kg` recompute".

    Design: Difficulty/compensating_invariant/cancel_fulfillment_conserves_roasted_kg
    """
    cat = setup_catalog(product_overrides={"base_price_cents_per_kg": 2000,
                                            "freshness_window_days": 60})
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 8)])
    ful = reserve_fulfillment(order["id"], prod["id"], lot["id"], 8)
    api.cancel_fulfillment(ful["id"], SALES)
    lot_read = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    assert lot_read["available_kg"] == 25.000, \
        f"available_kg must return to produced_kg 25.000 with zero drift, got {lot_read['available_kg']}"


# ─── combinatorial_formula / freshness_eligibility_nested_min_three_inputs ──

def test_freshness_eligible_at_nested_min_boundary(api):
    """PRD §3.5: "The effective ceiling is the smaller of the product's `freshness_window_days`
    and the freshness ceiling of the order account's price tier, namely its
    `freshness_max_days`. The lot is eligible only when its age in whole days is at most that
    effective ceiling; an age equal to the ceiling is still eligible, while an age one day
    beyond it is stale and the reservation is rejected with `ERR_STALE_ROAST`."

    Design: Difficulty/combinatorial_formula/freshness_eligibility_nested_min_three_inputs
    """
    clock_set("2026-06-01T00:00:00Z")
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 10},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 1_000_000},
        product_overrides={"base_price_cents_per_kg": 2200, "freshness_window_days": 14},
    )
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 5)])
    # Age 10 days == min(14, 10) = 10 -> inclusive boundary, eligible.
    clock_set("2026-06-11T00:00:00Z")
    rl = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    ful = validate_success(api.create_fulfillment(
        order["id"],
        create_fulfillment_payload(prod["id"], lot["id"], 5, rl["version"]), SALES), 201)
    assert ful["status"] == "RESERVED", \
        "age 10 == effective ceiling 10 must remain eligible (inclusive boundary)"
    assert ful["roast_date"] == "2026-06-01T00:00:00.000Z", \
        f"roast_date copied from the lot, got {ful['roast_date']}"


def test_freshness_stale_one_day_beyond_min_rejected(api):
    """PRD §3.5: "an age equal to the ceiling is still eligible, while an age one day beyond
    it is stale and the reservation is rejected with `ERR_STALE_ROAST`."

    Design: Difficulty/combinatorial_formula/freshness_eligibility_nested_min_three_inputs
    """
    clock_set("2026-06-01T00:00:00Z")
    cat = setup_catalog(
        tier_overrides={"discount_bps": 0, "freshness_max_days": 10},
        account_overrides={"net_terms_days": 30, "credit_limit_cents": 1_000_000},
        product_overrides={"base_price_cents_per_kg": 2200, "freshness_window_days": 14},
    )
    prod = cat["product"]
    _, lot = produce_roasted_lot(prod["id"], actual_green_kg=30, actual_roasted_kg=25)
    order = place_order(cat["account"]["id"], [order_line(prod["id"], 5)])
    # Age 11 days == min(14, 10) + 1 -> one beyond ceiling -> stale.
    clock_set("2026-06-12T00:00:00Z")
    rl = validate_success(api.get_roasted_lot(lot["id"], SALES), 200)
    res = api.create_fulfillment(
        order["id"], create_fulfillment_payload(prod["id"], lot["id"], 5, rl["version"]), SALES)
    validate_error(res, "ERR_STALE_ROAST")


# ─── entities / green_lot_computed_inventory_on_create (queue B) ────────────

def test_green_lot_computed_inventory_on_create(api):
    """PRD §3.3: "On receipt the lot's `on_hand_kg` equals `received_kg`, its `reserved_kg`
    is zero, its `available_kg` equals `received_kg`, and its `reorder_status` is computed
    per §2.7."

    Design: Corner/entities/green_lot_computed_inventory_on_create
    """
    lot = validate_success(api.create_green_lot(
        {"origin": "Ethiopia", "lot_ref": "ETH-CF", "received_kg": 80, "par_level_kg": 20},
        ROASTER), 201)
    assert lot["on_hand_kg"] == 80.000
    assert lot["available_kg"] == 80.000
    # available 80 >= par 20 -> OK.
    assert lot["reorder_status"] == "OK"
