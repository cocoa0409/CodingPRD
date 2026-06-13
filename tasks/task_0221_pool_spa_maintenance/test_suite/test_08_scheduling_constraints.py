"""Visit scheduling constraints: slot overlap, window containment, capacity,
interval validity, empty-route dispatch (PRD §3.2, §3.4)."""
from test_helpers import (
    validate_success, validate_error,
    setup_scheduled_visit_planned_route,
    create_customer, create_pool, create_active_plan, create_route, create_visit,
    create_visit_payload, ApiErrorId, TEST_USERS,
)

FT = TEST_USERS["field_technician_headers"]
RM = TEST_USERS["route_manager_headers"]
AM = TEST_USERS["account_manager_headers"]


def test_overlapping_visit_slot_rejected(api):
    """PRD §3.4: "it must not overlap the half-open slot of any existing non-terminal
    visit already on that route — though two visits may meet exactly at a boundary,
    since adjacency where one slot's end equals the next slot's start is allowed. A
    visit that spills outside the window or overlaps a sibling is rejected with
    `ERR_SLOT_OVERLAP`."

    An existing [540,600) visit rejects a new [580,640) that overlaps it.

    Design: Difficulty/resource_temporal_overlap/visit_slot_overlap_on_route_half_open
    """
    ctx = setup_scheduled_visit_planned_route(plan_type="RECURRING", frequency="WEEKLY",
                                              per_visit_rate_cents=6000, capacity_visits=5,
                                              slot_start_minute=540, slot_end_minute=600)
    resp = api.create_visit(create_visit_payload(
        ctx["pool"]["id"], ctx["plan"]["id"], ctx["route"]["id"],
        slot_start_minute=580, slot_end_minute=640), RM)
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_adjacent_visit_slot_accepted_at_boundary(api):
    """PRD §3.4: "two visits may meet exactly at a boundary, since adjacency where
    one slot's end equals the next slot's start is allowed."

    An existing [540,600) visit accepts a new [600,660) that touches only at 600.

    Design: Difficulty/resource_temporal_overlap/visit_slot_overlap_on_route_half_open
    """
    ctx = setup_scheduled_visit_planned_route(plan_type="RECURRING", frequency="WEEKLY",
                                              per_visit_rate_cents=6000, capacity_visits=5,
                                              slot_start_minute=540, slot_end_minute=600)
    resp = api.create_visit(create_visit_payload(
        ctx["pool"]["id"], ctx["plan"]["id"], ctx["route"]["id"],
        slot_start_minute=600, slot_end_minute=660), RM)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert data["slot_start_minute"] == 600


def test_visit_slot_outside_route_window_rejected(api):
    """PRD §3.4: "A visit that spills outside the window or overlaps a sibling is
    rejected with `ERR_SLOT_OVERLAP`."

    A slot [1000,1040) on a route window [480,1020) spills past the window end 1020.

    Design: Difficulty/resource_temporal_overlap/visit_slot_outside_route_window
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = create_active_plan(pool["id"], plan_type="RECURRING", frequency="WEEKLY", per_visit_rate_cents=6000)
    route = create_route(window_start_minute=480, window_end_minute=1020, capacity_visits=5)
    resp = api.create_visit(create_visit_payload(
        pool["id"], plan["id"], route["id"], slot_start_minute=1000, slot_end_minute=1040), RM)
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP.value)


def test_visit_slot_within_window_accepted(api):
    """PRD §3.4: "Its half-open slot must lie entirely within the route's half-open
    window, and it must not overlap the half-open slot of any existing non-terminal
    visit already on that route — though two visits may meet exactly at a boundary,
    since adjacency where one slot's end equals the next slot's start is allowed."

    A slot [980,1020) ends exactly at the window end 1020, which is permitted under
    half-open containment.

    Design: Difficulty/resource_temporal_overlap/visit_slot_outside_route_window
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = create_active_plan(pool["id"], plan_type="RECURRING", frequency="WEEKLY", per_visit_rate_cents=6000)
    route = create_route(window_start_minute=480, window_end_minute=1020, capacity_visits=5)
    resp = api.create_visit(create_visit_payload(
        pool["id"], plan["id"], route["id"], slot_start_minute=980, slot_end_minute=1020), RM)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_route_at_capacity_rejects_new_visit(api):
    """PRD §3.4: "a route that is already full — meaning its count of non-terminal
    visits equals its `capacity_visits` — rejects any further visit with
    `ERR_ROUTE_AT_CAPACITY`."

    A route with capacity_visits 1 holding one SCHEDULED visit rejects the next.

    Design: Difficulty/boundary_precision_check/route_at_capacity_boundary_empty_slot_count
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = create_active_plan(pool["id"], plan_type="RECURRING", frequency="WEEKLY", per_visit_rate_cents=6000)
    route = create_route(capacity_visits=1)
    create_visit(pool["id"], plan["id"], route["id"], slot_start_minute=540, slot_end_minute=600)
    resp = api.create_visit(create_visit_payload(
        pool["id"], plan["id"], route["id"], slot_start_minute=600, slot_end_minute=660), RM)
    validate_error(resp, ApiErrorId.ERR_ROUTE_AT_CAPACITY.value)


def test_route_below_capacity_accepts_new_visit(api):
    """PRD §3.4: "a route that is already full — meaning its count of non-terminal
    visits equals its `capacity_visits` — rejects any further visit with
    `ERR_ROUTE_AT_CAPACITY`."

    A route with capacity_visits 2 holding one visit is below capacity, so a second
    visit is accepted (count 1 < capacity 2).

    Design: Difficulty/boundary_precision_check/route_at_capacity_boundary_empty_slot_count
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = create_active_plan(pool["id"], plan_type="RECURRING", frequency="WEEKLY", per_visit_rate_cents=6000)
    route = create_route(capacity_visits=2)
    create_visit(pool["id"], plan["id"], route["id"], slot_start_minute=540, slot_end_minute=600)
    resp = api.create_visit(create_visit_payload(
        pool["id"], plan["id"], route["id"], slot_start_minute=600, slot_end_minute=660), RM)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_invalid_interval_visit_slot_rejected(api):
    """PRD §3.4: "As with route windows, `slot_end_minute` must be strictly greater
    than `slot_start_minute`, and a slot that fails this is rejected with
    `ERR_INVALID_INTERVAL`."

    Design: Corner/validations/invalid_interval_visit_slot_returns_error
    """
    customer = create_customer()
    pool = create_pool(customer["id"])
    plan = create_active_plan(pool["id"], plan_type="RECURRING", frequency="WEEKLY", per_visit_rate_cents=6000)
    route = create_route(capacity_visits=5)
    resp = api.create_visit(create_visit_payload(
        pool["id"], plan["id"], route["id"], slot_start_minute=600, slot_end_minute=600), RM)
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL.value)


def test_dispatch_empty_route_rejected(api):
    """PRD §3.2: "A route may be dispatched only when it currently holds at least one
    visit in `SCHEDULED`; dispatching an empty route is rejected with
    `ERR_EMPTY_ROUTE`."

    Design: Corner/state_machines/dispatch_empty_route_returns_empty_route
    """
    route = create_route(capacity_visits=5)
    resp = api.dispatch_route(route["id"], RM)
    validate_error(resp, ApiErrorId.ERR_EMPTY_ROUTE.value)
