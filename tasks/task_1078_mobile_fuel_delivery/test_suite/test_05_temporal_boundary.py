"""Temporal-overlap geometry and numeric boundary precision.

Queue A: resource_temporal_overlap (truck half-open windows, vehicle closed+buffer),
boundary_precision_check (tank headroom exact, route capacity at max_stops).
"""
from test_helpers import (
    validate_success, validate_error,
    make_member_headers,
    setup_truck_with_route, setup_vehicle_with_scheduled_order,
    setup_individual_vehicle, setup_route_at_capacity,
    new_order, get_route,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


# ─── Queue A: resource_temporal_overlap / truck half-open windows ───────────

def test_truck_overlapping_route_window_rejected(api):
    """PRD §3.5: "At creation the platform enforces that a single truck never runs two
    overlapping routes: the new route's half-open window must not overlap any existing
    non-terminal route on the same truck."
    PRD §3.5: "any genuine overlap is rejected with `ERR_TRUCK_ROUTE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/truck_route_halfopen_window_overlap_rejected
    """
    ctx = setup_truck_with_route(window_start="2026-05-02T08:00:00Z",
                                 window_end="2026-05-02T12:00:00Z")
    res = api.create_route(
        {"truck_id": ctx["truck_id"], "assigned_driver_id": ctx["driver_id"], "zone": "ZONE_A",
         "window_start": "2026-05-02T11:00:00Z", "window_end": "2026-05-02T14:00:00Z"},
        DISPATCHER)
    validate_error(res, "ERR_TRUCK_ROUTE_OVERLAP", expected_status=409)


def test_truck_touching_route_window_allowed(api):
    """PRD §3.5: "Because the interval is half-open, two windows that merely touch — where
    one window's end instant equals the other's start instant — do not overlap and are
    allowed; any genuine overlap is rejected with `ERR_TRUCK_ROUTE_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/truck_route_halfopen_window_overlap_rejected
    """
    ctx = setup_truck_with_route(window_start="2026-05-02T08:00:00Z",
                                 window_end="2026-05-02T12:00:00Z")
    # New window starts exactly at the prior window's end instant -> adjacency, not overlap.
    res = api.create_route(
        {"truck_id": ctx["truck_id"], "assigned_driver_id": ctx["driver_id"], "zone": "ZONE_A",
         "window_start": "2026-05-02T12:00:00Z", "window_end": "2026-05-02T15:00:00Z"},
        DISPATCHER)
    route = validate_success(res, 201)
    assert route["status"] == "PLANNING"


# ─── Queue A: resource_temporal_overlap / vehicle closed + 60-min buffer ─────

def test_vehicle_window_within_buffer_rejected(api):
    """PRD §3.4: "the new order's window must be separated from every other non-terminal
    order window on the same vehicle by at least 60 minutes, measured as the gap between the
    nearest endpoints of the two windows. Two windows that overlap, that merely touch at an
    endpoint, or that are less than 60 minutes apart all conflict and are rejected with
    `ERR_VEHICLE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/vehicle_order_window_buffer_conflict_rejected
    """
    ctx = setup_vehicle_with_scheduled_order(
        window_start="2026-05-02T09:00:00Z", window_end="2026-05-02T10:00:00Z",
        make_model="Beetle")
    # New window starts 30 minutes after the prior window's end -> inside the 60-min buffer.
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_id"], "zone": "ZONE_A",
         "delivery_address": "1 Buf St", "requested_gallons": 5,
         "delivery_window_start": "2026-05-02T10:30:00Z",
         "delivery_window_end": "2026-05-02T11:30:00Z"},
        make_member_headers(ctx["customer_id"]))
    validate_error(res, "ERR_VEHICLE_WINDOW_CONFLICT", expected_status=409)


def test_vehicle_window_exactly_60_minutes_apart_allowed(api):
    """PRD §3.4: "the new order's window must be separated from every other non-terminal
    order window on the same vehicle by at least 60 minutes, measured as the gap between the
    nearest endpoints of the two windows."

    Design: Difficulty/resource_temporal_overlap/vehicle_order_window_buffer_conflict_rejected
    """
    ctx = setup_vehicle_with_scheduled_order(
        window_start="2026-05-02T09:00:00Z", window_end="2026-05-02T10:00:00Z",
        make_model="Beetle")
    # New window starts exactly 60 minutes after the prior end -> "at least 60" is satisfied.
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_id"], "zone": "ZONE_A",
         "delivery_address": "1 Buf St", "requested_gallons": 5,
         "delivery_window_start": "2026-05-02T11:00:00Z",
         "delivery_window_end": "2026-05-02T12:00:00Z"},
        make_member_headers(ctx["customer_id"]))
    order = validate_success(res, 201)
    assert order["status"] == "SCHEDULED"


# ─── Queue A: boundary_precision_check / tank headroom exact equal ──────────

def test_requested_gallons_exactly_equal_headroom_allowed(api):
    """PRD §3.4: "the `requested_gallons` must fit the vehicle's tank headroom, defined as
    `tank_capacity_gallons` minus `current_fuel_level_gallons`; a request that exceeds that
    headroom is rejected with `ERR_EXCEEDS_TANK_CAPACITY`."

    Design: Difficulty/boundary_precision_check/tank_headroom_exact_equal_is_allowed
    """
    ctx = setup_individual_vehicle(tank_capacity_gallons=15, current_fuel_level_gallons=3)
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_id"], "zone": "ZONE_A",
         "delivery_address": "12 Edge St", "requested_gallons": 12,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(ctx["customer_id"]))
    order = validate_success(res, 201)
    assert order["status"] == "SCHEDULED"
    assert order["estimated_fuel_cost_cents"] == 5028, "12 gal * 419 = 5028"


def test_requested_gallons_one_over_headroom_rejected(api):
    """PRD §3.4: "the `requested_gallons` must fit the vehicle's tank headroom, defined as
    `tank_capacity_gallons` minus `current_fuel_level_gallons`; a request that exceeds that
    headroom is rejected with `ERR_EXCEEDS_TANK_CAPACITY`."

    Design: Difficulty/boundary_precision_check/tank_headroom_exact_equal_is_allowed
    """
    ctx = setup_individual_vehicle(tank_capacity_gallons=15, current_fuel_level_gallons=3)
    # headroom is 12; requesting 13 exceeds it by one gallon.
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_id"], "zone": "ZONE_A",
         "delivery_address": "13 Edge St", "requested_gallons": 13,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(ctx["customer_id"]))
    validate_error(res, "ERR_EXCEEDS_TANK_CAPACITY", expected_status=422)


# ─── Queue A: boundary_precision_check / route capacity at max_stops ─────────

def test_assign_route_rejected_at_exact_max_stops(api):
    """PRD §3.5: "The route must have capacity — its `stop_count` must be strictly less than
    its `max_stops`, or the assignment is rejected with `ERR_ROUTE_AT_CAPACITY`."

    Design: Difficulty/boundary_precision_check/route_capacity_reject_at_exact_max_stops
    """
    ctx = setup_route_at_capacity()
    res = api.assign_route(ctx["order_b"], {"route_id": ctx["route_id"]}, DISPATCHER)
    validate_error(res, "ERR_ROUTE_AT_CAPACITY", expected_status=409)


def test_route_stop_count_unchanged_after_capacity_reject(api):
    """PRD §3.5: "The route must have capacity — its `stop_count` must be strictly less than
    its `max_stops`, or the assignment is rejected with `ERR_ROUTE_AT_CAPACITY`."

    Design: Difficulty/boundary_precision_check/route_capacity_reject_at_exact_max_stops
    """
    ctx = setup_route_at_capacity()
    api.assign_route(ctx["order_b"], {"route_id": ctx["route_id"]}, DISPATCHER)
    assert get_route(ctx["route_id"])["stop_count"] == 1, "rejected assign does not add a stop"
