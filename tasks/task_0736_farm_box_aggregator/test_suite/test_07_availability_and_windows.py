"""Boundary and interval-geometry rules: availability quantity, delivery-slot overlap,
market-cycle window buffer.

Difficulty instances: boundary_precision_check (availability), resource_temporal_overlap
(delivery slots half-open aggregate capacity; cycle window closed interval + buffer).
"""
from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    make_admin_headers, make_customer_headers,
    set_clock, new_farm, new_hub, new_customer, new_product, new_cycle, new_offering,
    open_cycle, new_order, new_line, do_checkout,
    assert_offering,
)


def _offering(api, offering_id):
    return api.get_offering(offering_id, make_admin_headers()).json()["data"]


def _order(api, order_id):
    return api.get_order(order_id, make_admin_headers()).json()["data"]


# ---------------------------------------------------------------------------
# boundary_precision_check / availability_qty_exact_boundary_addline
# ---------------------------------------------------------------------------
def _remaining_two_world(api):
    """OPEN cycle, egg offering offered_qty 5; order1 reserves 3 (checked-out qty3 line) leaving
    remaining_qty 2; order2 left in CART in the still-OPEN cycle."""
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api)
    customer = new_customer(api, snap_balance_cents=0)
    egg = new_product(api, farm["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
                      unit_price_cents=400, snap_eligible=False)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], egg["id"], offered_qty=5)
    open_cycle(api, cycle["id"])
    order1 = new_order(api, customer["id"], cycle["id"], hub["id"])
    new_line(api, customer["id"], order1["id"], offering["id"], 3)
    do_checkout(api, customer["id"], order1["id"])
    order2 = new_order(api, customer["id"], cycle["id"], hub["id"])
    return {"customer": customer, "offering": offering, "order2": order2}


def test_addline_at_exact_remaining_boundary_succeeds(api):
    """PRD §3.5: "The requested units may not exceed the offering's current `remaining_qty`; a
    request that would oversell the offering is rejected with `ERR_INSUFFICIENT_AVAILABILITY`."

    Design: Difficulty/boundary_precision_check/availability_qty_exact_boundary_addline
    """
    world = _remaining_two_world(api)
    resp = api.add_line(world["order2"]["id"], {"offering_id": world["offering"]["id"], "requested_qty": 2},
                        make_customer_headers(world["customer"]["id"]))
    validate_success(resp, 201)  # requested_qty 2 == remaining_qty 2 does not exceed
    offering = _offering(api, world["offering"]["id"])
    assert_offering(offering)
    assert offering["remaining_qty"] == 0
    assert offering["reserved_qty"] == 5


def test_addline_one_over_remaining_boundary_rejected(api):
    """PRD §3.5: "The requested units may not exceed the offering's current `remaining_qty`; a
    request that would oversell the offering is rejected with `ERR_INSUFFICIENT_AVAILABILITY`."

    Design: Difficulty/boundary_precision_check/availability_qty_exact_boundary_addline
    """
    world = _remaining_two_world(api)
    resp = api.add_line(world["order2"]["id"], {"offering_id": world["offering"]["id"], "requested_qty": 3},
                        make_customer_headers(world["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_AVAILABILITY.value, 409)  # 3 == remaining 2 + 1


# ---------------------------------------------------------------------------
# resource_temporal_overlap / delivery_slot_overlap_aggregate_capacity_halfopen
# ---------------------------------------------------------------------------
def _delivery_hub_with_booked_slot(api):
    """DELIVERY hub slot_capacity 1; OPEN cycle; egg offering; order1 booked for
    [10:00, 11:00) via checkout."""
    set_clock(api)
    farm = new_farm(api, snap_authorized=True)
    hub = new_hub(api, name="Van Route A", hub_type="DELIVERY", slot_capacity=1)
    customer = new_customer(api, snap_balance_cents=0)
    egg = new_product(api, farm["id"], name="Eggs", category="DAIRY", pricing_mode="FIXED",
                      unit_price_cents=400, snap_eligible=False)
    cycle = new_cycle(api)
    offering = new_offering(api, cycle["id"], farm["id"], egg["id"], offered_qty=100)
    open_cycle(api, cycle["id"])
    order1 = new_order(api, customer["id"], cycle["id"], hub["id"], fulfillment_type="DELIVERY",
                       delivery_slot_start="2026-06-06T10:00:00Z", delivery_slot_end="2026-06-06T11:00:00Z")
    new_line(api, customer["id"], order1["id"], offering["id"], 1)
    do_checkout(api, customer["id"], order1["id"])
    return {"customer": customer, "hub": hub, "cycle": cycle, "offering": offering}


def _second_delivery_order(api, world, start, end):
    order2 = new_order(api, world["customer"]["id"], world["cycle"]["id"], world["hub"]["id"],
                       fulfillment_type="DELIVERY", delivery_slot_start=start, delivery_slot_end=end)
    new_line(api, world["customer"]["id"], order2["id"], world["offering"]["id"], 1)
    return order2


def test_overlapping_delivery_slot_over_capacity_rejected(api):
    """PRD §3.6: "If admitting the order would push the overlap count above `slot_capacity`,
    checkout is rejected with `ERR_SLOT_CAPACITY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/delivery_slot_overlap_aggregate_capacity_halfopen
    """
    world = _delivery_hub_with_booked_slot(api)
    order2 = _second_delivery_order(api, world, "2026-06-06T10:30:00Z", "2026-06-06T11:30:00Z")
    resp = api.checkout_order(order2["id"], make_customer_headers(world["customer"]["id"]))
    validate_error(resp, ApiErrorId.ERR_SLOT_CAPACITY_EXCEEDED.value, 409)
    assert _order(api, order2["id"])["order_status"] == "CART"


def test_adjacent_touching_delivery_slot_admitted(api):
    """PRD §3.6: "Intervals that merely touch — where one's end equals another's start — do not
    count as overlapping."

    Design: Difficulty/resource_temporal_overlap/delivery_slot_overlap_aggregate_capacity_halfopen
    """
    world = _delivery_hub_with_booked_slot(api)
    # [11:00, 12:00) starts exactly where the booked [10:00, 11:00) ends -> no overlap.
    order2 = _second_delivery_order(api, world, "2026-06-06T11:00:00Z", "2026-06-06T12:00:00Z")
    resp = api.checkout_order(order2["id"], make_customer_headers(world["customer"]["id"]))
    data = validate_success(resp, 200)
    assert data["order_status"] == "PLACED"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / cycle_window_buffer_conflict_closed_interval
# ---------------------------------------------------------------------------
def test_same_region_cycle_inside_buffer_conflicts(api):
    """PRD §3.2: "a new cycle is rejected with `ERR_CYCLE_WINDOW_CONFLICT` when another cycle in
    the same `region_code` has a `[order_open_at, fulfillment_date]` window that falls within 24
    hours of the new cycle's window; both windows are treated as closed intervals and the 24-hour
    buffer separates them, so two same-region windows conflict whenever the gap between them is
    less than 24 hours."

    Design: Difficulty/resource_temporal_overlap/cycle_window_buffer_conflict_closed_interval
    """
    set_clock(api)
    new_cycle(api, cycle_code="C1", region_code="R1",
              order_open_at="2026-06-02T00:00:00Z", order_cutoff_at="2026-06-05T00:00:00Z",
              fulfillment_date="2026-06-06T00:00:00Z")
    # Opens 12h after the prior fulfillment (06-06T00:00Z) -> inside the 24h buffer.
    resp = api.create_cycle(
        {"cycle_code": "C2", "region_code": "R1",
         "order_open_at": "2026-06-06T12:00:00Z", "order_cutoff_at": "2026-06-09T00:00:00Z",
         "fulfillment_date": "2026-06-10T00:00:00Z"},
        make_admin_headers(),
    )
    validate_error(resp, ApiErrorId.ERR_CYCLE_WINDOW_CONFLICT.value, 409)


def test_different_region_overlapping_window_allowed(api):
    """PRD §3.2: "a new cycle is rejected with `ERR_CYCLE_WINDOW_CONFLICT` when another cycle in
    the same `region_code` has a `[order_open_at, fulfillment_date]` window that falls within 24
    hours of the new cycle's window; both windows are treated as closed intervals and the 24-hour
    buffer separates them, so two same-region windows conflict whenever the gap between them is
    less than 24 hours."

    Design: Difficulty/resource_temporal_overlap/cycle_window_buffer_conflict_closed_interval
    """
    set_clock(api)
    new_cycle(api, cycle_code="C1", region_code="R1",
              order_open_at="2026-06-02T00:00:00Z", order_cutoff_at="2026-06-05T00:00:00Z",
              fulfillment_date="2026-06-06T00:00:00Z")
    # Identical window but a DIFFERENT region_code -> the conflict is region-scoped, so it is allowed.
    resp = api.create_cycle(
        {"cycle_code": "C2", "region_code": "R2",
         "order_open_at": "2026-06-02T00:00:00Z", "order_cutoff_at": "2026-06-05T00:00:00Z",
         "fulfillment_date": "2026-06-06T00:00:00Z"},
        make_admin_headers(),
    )
    validate_success(resp, 201)
