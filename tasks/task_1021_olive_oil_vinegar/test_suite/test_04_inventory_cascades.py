"""Reservation/fusti cascades on fulfill and cancel, reorder-point boundary, volume
conservation, replenishment receive, and FEFO vessel selection."""
import pytest
from test_helpers import (
    validate_success, validate_paginated, ApiErrorId,
    create_member, create_bulk_product, create_fusti, create_order, pay_order,
    fulfill_order, cancel_order, get_reservation_for_order, setup_refill_order_paid,
    refill_line, TEST_USERS,
)

STAFF = TEST_USERS["shop_staff_headers"]
INV = TEST_USERS["inventory_manager_headers"]


# ── Difficulty: transitive_cascade / fulfill_commit_draws_volume_trips_low_creates_replenishment ──

def test_fulfill_commits_reservation_and_draws_physical_volume(api):
    """PRD §3.5: "Each held `Reservation` then moves `HELD → COMMITTED`: its vessel's
    `current_volume_ml` and `reserved_volume_ml` are both reduced by the reservation's
    `volume_ml`, and the vessel's `first_draw_at` is set to the logical now if it was null
    (opening the sensory decay curve)."

    Design: Difficulty/transitive_cascade/fulfill_commit_draws_volume_trips_low_creates_replenishment
    """
    member, product, fusti, order = setup_refill_order_paid(
        api, volume_ml=1000, initial_volume_ml=6000, reorder_point_ml=5000)
    res = get_reservation_for_order(api, order["id"])
    fulfill_order(api, order)
    res_after = validate_success(api.get_reservation(res["id"], STAFF))
    assert res_after["status"] == "COMMITTED", res_after["status"]
    fusti_after = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_after["current_volume_ml"] == 5000, fusti_after["current_volume_ml"]
    assert fusti_after["reserved_volume_ml"] == 0, fusti_after["reserved_volume_ml"]


def test_fulfill_trips_low_and_spawns_replenishment_order(api):
    """PRD §3.2: "When a fulfillment draws a vessel down to at or below its reorder point while
    some volume remains, the vessel auto-transitions `IN_SERVICE → LOW`". PRD §3.2: "Any
    transition into `LOW` or `EMPTY` spawns a `ReplenishmentOrder` in `REQUESTED` status, whose
    `fusti_id` and `product_id` are copied from the vessel and whose `requested_volume_ml` is the
    capacity minus the current volume at that moment."

    Design: Difficulty/transitive_cascade/fulfill_commit_draws_volume_trips_low_creates_replenishment
    """
    member, product, fusti, order = setup_refill_order_paid(
        api, volume_ml=1000, initial_volume_ml=6000, reorder_point_ml=5000)
    fulfill_order(api, order)
    fusti_after = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_after["status"] == "LOW", fusti_after["status"]
    rows, _meta = validate_paginated(
        api.list_replenishment_orders(STAFF, params={"fusti_id": fusti["id"]}))
    assert len(rows) == 1, f"expected exactly one replenishment order, got {len(rows)}"
    assert rows[0]["status"] == "REQUESTED"
    assert rows[0]["requested_volume_ml"] == 5000, rows[0]["requested_volume_ml"]


# ── Difficulty: transitive_cascade / cancel_releases_reservation_returns_reserved_volume ──

def test_cancel_releases_held_reservation(api):
    """PRD §3.6: "every `HELD` reservation moves `HELD → RELEASED`, its vessel's
    `reserved_volume_ml` is reduced by the held `volume_ml` while its `current_volume_ml` stays
    unchanged".

    Design: Difficulty/transitive_cascade/cancel_releases_reservation_returns_reserved_volume
    """
    member, product, fusti, order = setup_refill_order_paid(
        api, volume_ml=1000, initial_volume_ml=6000, reorder_point_ml=2000)
    res = get_reservation_for_order(api, order["id"])
    cancel_order(api, order, member=member)
    res_after = validate_success(api.get_reservation(res["id"], STAFF))
    assert res_after["status"] == "RELEASED", res_after["status"]
    fusti_after = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_after["reserved_volume_ml"] == 0, fusti_after["reserved_volume_ml"]


def test_cancel_release_leaves_physical_volume_unchanged(api):
    """PRD §3.6: "every `HELD` reservation moves `HELD → RELEASED`, its vessel's
    `reserved_volume_ml` is reduced by the held `volume_ml` while its `current_volume_ml` stays
    unchanged".

    Design: Difficulty/transitive_cascade/cancel_releases_reservation_returns_reserved_volume
    """
    member, product, fusti, order = setup_refill_order_paid(
        api, volume_ml=1000, initial_volume_ml=6000, reorder_point_ml=2000)
    cancel_order(api, order, member=member)
    fusti_after = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_after["current_volume_ml"] == 6000, fusti_after["current_volume_ml"]


# ── Difficulty: boundary_precision_check / fusti_reorder_point_inclusive_boundary ──

def test_draw_landing_exactly_on_reorder_point_trips_low(api):
    """PRD §3.2: "When a fulfillment draws a vessel down to at or below its reorder point while
    some volume remains, the vessel auto-transitions `IN_SERVICE → LOW`".

    Design: Difficulty/boundary_precision_check/fusti_reorder_point_inclusive_boundary
    """
    member, product, fusti, order = setup_refill_order_paid(
        api, volume_ml=1000, initial_volume_ml=6000, reorder_point_ml=5000)
    fulfill_order(api, order)
    fusti_after = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_after["current_volume_ml"] == 5000
    assert fusti_after["status"] == "LOW", f"5000 == reorder must be LOW, got {fusti_after['status']}"


def test_draw_landing_one_above_reorder_point_stays_in_service(api):
    """PRD §3.2: "When a fulfillment draws a vessel down to at or below its reorder point while
    some volume remains, the vessel auto-transitions `IN_SERVICE → LOW`".

    Design: Difficulty/boundary_precision_check/fusti_reorder_point_inclusive_boundary
    """
    member, product, fusti, order = setup_refill_order_paid(
        api, volume_ml=999, initial_volume_ml=6000, reorder_point_ml=5000)
    fulfill_order(api, order)
    fusti_after = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_after["current_volume_ml"] == 5001
    assert fusti_after["status"] == "IN_SERVICE", \
        f"5001 > reorder must stay IN_SERVICE, got {fusti_after['status']}"


# ── Difficulty: compensating_invariant / fusti_physical_volume_conserved_across_reserve_and_release ──

def test_reserve_leg_holds_volume_without_touching_physical(api):
    """PRD §3.4: "For each satisfied refill line the system creates a `Reservation` in `HELD`
    status recording its `order_id`, its selected `fusti_id`, and the `volume_ml` held, and
    increases the chosen vessel's `reserved_volume_ml` by that volume (its current volume is
    untouched at this stage)."

    Design: Difficulty/compensating_invariant/fusti_physical_volume_conserved_across_reserve_and_release
    """
    member, product, fusti, order = setup_refill_order_paid(
        api, volume_ml=1000, initial_volume_ml=6000, reorder_point_ml=2000)
    fusti_after = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_after["reserved_volume_ml"] == 1000, fusti_after["reserved_volume_ml"]
    assert fusti_after["current_volume_ml"] == 6000, fusti_after["current_volume_ml"]


def test_reserve_then_release_conserves_physical_volume(api):
    """PRD §3.6: "every `HELD` reservation moves `HELD → RELEASED`, its vessel's
    `reserved_volume_ml` is reduced by the held `volume_ml` while its `current_volume_ml` stays
    unchanged".

    Design: Difficulty/compensating_invariant/fusti_physical_volume_conserved_across_reserve_and_release
    """
    member, product, fusti, order = setup_refill_order_paid(
        api, volume_ml=1000, initial_volume_ml=6000, reorder_point_ml=2000)
    cancel_order(api, order, member=member)
    fusti_after = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_after["current_volume_ml"] == 6000, fusti_after["current_volume_ml"]
    assert fusti_after["reserved_volume_ml"] == 0, fusti_after["reserved_volume_ml"]


# ── Corner: cross_cutting_complexity_layers / replenishment_receive_returns_fusti_to_service ──

def test_receive_replenishment_refills_and_returns_to_service(api):
    """PRD §3.2: "receiving refills the linked vessel's `current_volume_ml` to its full capacity,
    sets the vessel's `harvest_date` to the received harvest date, recomputes the `best_by_date`,
    resets `first_draw_at` to null, and returns the vessel from `LOW` or `EMPTY` to `IN_SERVICE`,
    while the replenishment order moves `REQUESTED → RECEIVED`."

    Design: Corner/cross_cutting_complexity_layers/replenishment_receive_returns_fusti_to_service
    """
    member, product, fusti, order = setup_refill_order_paid(
        api, volume_ml=1000, initial_volume_ml=6000, reorder_point_ml=5000)
    fulfill_order(api, order)
    rows, _meta = validate_paginated(
        api.list_replenishment_orders(STAFF, params={"fusti_id": fusti["id"]}))
    ro_id = rows[0]["id"]
    ro = validate_success(api.receive_replenishment(
        ro_id, {"received_harvest_date": "2026-07-10T00:00:00Z"}, STAFF))
    assert ro["status"] == "RECEIVED", ro["status"]
    fusti_after = validate_success(api.get_fusti(fusti["id"], INV))
    assert fusti_after["current_volume_ml"] == 10000, fusti_after["current_volume_ml"]
    assert fusti_after["status"] == "IN_SERVICE", fusti_after["status"]


# ── Corner: cross_cutting_complexity_layers / fefo_selector_picks_earliest_best_by ──

def test_pay_reserves_against_earliest_best_by_vessel(api):
    """PRD §3.4: "The candidates are the vessels for the line's product that are `IN_SERVICE` or
    `LOW`, are not past their best-by, and have an `available_volume_ml` of at least the line's
    `volume_ml`; among them the vessel with the earliest best-by date wins, breaking ties by the
    earliest creation timestamp."

    Design: Corner/cross_cutting_complexity_layers/fefo_selector_picks_earliest_best_by
    """
    member = create_member(api)
    product = create_bulk_product(api, price_per_ml_cents=0.30, shelf_life_days=540)
    fusti_a = create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                           reorder_point_ml=1000, harvest_date="2026-01-01T00:00:00Z")
    fusti_b = create_fusti(api, product["id"], capacity_ml=10000, initial_volume_ml=10000,
                           reorder_point_ml=1000, harvest_date="2026-06-01T00:00:00Z")
    order = create_order(api, member, [refill_line(product["id"], 500)])
    pay_order(api, member, order)
    a_after = validate_success(api.get_fusti(fusti_a["id"], INV))
    b_after = validate_success(api.get_fusti(fusti_b["id"], INV))
    assert a_after["reserved_volume_ml"] == 500, "earlier best-by (A) must be chosen (FEFO)"
    assert b_after["reserved_volume_ml"] == 0, "later best-by (B) must not be reserved"
