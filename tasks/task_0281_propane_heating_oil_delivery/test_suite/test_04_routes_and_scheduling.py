"""Trucks, routes, order scheduling, capacity reservation, and route windows.

Translates queue A (Difficulty) rules resource_temporal_overlap (route window),
boundary_precision_check (route capacity), cross_entity_state_dependency
(assign requires PLANNING route), and compensating_invariant (truck capacity
conserved across assign/unassign), plus queue B (Corner) scheduling instances.
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_route_payload, assign_order_payload,
    assert_route_reservation_conserved,
)
from test_helpers import fixtures as fx

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]


# ---------------------------------------------------------------------------
# Difficulty: resource_temporal_overlap — route window + turnaround buffer
# ---------------------------------------------------------------------------
def test_route_window_buffer_conflict_on_truck(api):
    """PRD §3.5: "two routes conflict if their windows, each extended by the turnaround buffer, touch or overlap. A collision is rejected with `ERR_ROUTE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/route_window_buffer_conflict_on_truck
    """
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000,
                            turnaround_buffer_minutes=60)
    fx.create_route(truck["id"], route_date="2026-02-11T00:00:00Z",
                    window_start="2026-02-11T09:00:00Z",
                    window_end="2026-02-11T12:00:00Z")
    # New window 12:30-14:00: gap to the existing 09:00-12:00 route is 30 min < the
    # 60-min buffer, so the buffer-extended windows overlap -> conflict.
    resp = api.create_route(truck["id"], create_route_payload(
        route_date="2026-02-11T00:00:00Z",
        window_start="2026-02-11T12:30:00Z",
        window_end="2026-02-11T14:00:00Z"), DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT.value)


def test_route_window_direct_overlap_conflict_on_truck(api):
    """PRD §3.5: "two routes conflict if their windows, each extended by the turnaround buffer, touch or overlap. A collision is rejected with `ERR_ROUTE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/route_window_buffer_conflict_on_truck
    """
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000,
                            turnaround_buffer_minutes=60)
    fx.create_route(truck["id"], route_date="2026-02-11T00:00:00Z",
                    window_start="2026-02-11T09:00:00Z",
                    window_end="2026-02-11T12:00:00Z")
    # A window fully inside the existing one overlaps directly (independent of the
    # buffer), so it must be rejected under "their windows ... touch or overlap".
    resp = api.create_route(truck["id"], create_route_payload(
        route_date="2026-02-11T00:00:00Z",
        window_start="2026-02-11T10:00:00Z",
        window_end="2026-02-11T11:00:00Z"), DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_WINDOW_CONFLICT.value)


# ---------------------------------------------------------------------------
# Difficulty: boundary_precision_check — route capacity exact fit vs overflow
# ---------------------------------------------------------------------------
def test_route_capacity_exact_fit_succeeds(api):
    """PRD §3.6: "adding this order's `requested_gallons` must keep the route within the truck's limit, meaning the route's existing `reserved_gallons` plus this order's `requested_gallons` must not exceed the truck's `daily_capacity_gallons` (else `ERR_ROUTE_CAPACITY_EXCEEDED`)."

    Design: Difficulty/boundary_precision_check/route_capacity_exact_fit_succeeds_overflow_rejected
    """
    base = fx.setup_account_with_passed_tank(tank_overrides={"capacity_gallons": 2000,
                                                             "k_factor": 1500,
                                                             "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"])
    o1 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=600)
    fx.assign_order(account["id"], o1["id"], route["id"])
    o2 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=400)
    # 600 + 400 == 1000 exactly, allowed (<=).
    scheduled = validate_success(api.assign_order(
        account["id"], o2["id"], assign_order_payload(route["id"]), DISP))
    assert scheduled["status"] == "SCHEDULED"


def test_route_capacity_overflow_rejected(api):
    """PRD §3.6: "the route's existing `reserved_gallons` plus this order's `requested_gallons` must not exceed the truck's `daily_capacity_gallons` (else `ERR_ROUTE_CAPACITY_EXCEEDED`)."

    Design: Difficulty/boundary_precision_check/route_capacity_exact_fit_succeeds_overflow_rejected
    """
    base = fx.setup_account_with_passed_tank(tank_overrides={"capacity_gallons": 2000,
                                                             "k_factor": 1500,
                                                             "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"])
    o1 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=600)
    fx.assign_order(account["id"], o1["id"], route["id"])
    o2 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=400)
    fx.assign_order(account["id"], o2["id"], route["id"])  # reserved now 1000
    o3 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=1)
    # 1000 + 1 > 1000 rejected.
    resp = api.assign_order(account["id"], o3["id"], assign_order_payload(route["id"]), DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED.value)


# ---------------------------------------------------------------------------
# Difficulty: cross_entity_state_dependency — assign requires PLANNING route
# ---------------------------------------------------------------------------
def test_order_assign_requires_route_planning(api):
    """PRD §3.6: "the target route must be in `PLANNING` (else `ERR_ROUTE_NOT_PLANNING`)"

    Design: Difficulty/cross_entity_state_dependency/order_assign_requires_route_planning
    """
    base = fx.setup_account_with_passed_tank(tank_overrides={"capacity_gallons": 800,
                                                             "k_factor": 1500,
                                                             "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"])
    o1 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], o1["id"], route["id"])
    fx.dispatch_route(truck["id"], route["id"])  # route now DISPATCHED
    o2 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=150)
    resp = api.assign_order(account["id"], o2["id"], assign_order_payload(route["id"]), DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNING.value)


def test_order_assign_to_cancelled_route_rejected(api):
    """PRD §3.6: "the target route must be in `PLANNING` (else `ERR_ROUTE_NOT_PLANNING`)"

    Design: Difficulty/cross_entity_state_dependency/order_assign_requires_route_planning
    """
    base = fx.setup_account_with_passed_tank(tank_overrides={"capacity_gallons": 800,
                                                             "k_factor": 1500,
                                                             "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"])
    # A CANCELLED route is also not in PLANNING, so assign is rejected the same way.
    validate_success(api.cancel_route(truck["id"], route["id"], DISP))
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    resp = api.assign_order(account["id"], order["id"], assign_order_payload(route["id"]), DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNING.value)


# ---------------------------------------------------------------------------
# Difficulty: compensating_invariant — capacity conserved across assign/unassign
# ---------------------------------------------------------------------------
def test_truck_capacity_conserved_across_assign_unassign(api):
    """PRD §2.5: "A route's `reserved_gallons` is a conserved quantity: it is the running sum of `requested_gallons` over the orders currently holding a reservation on that route, and every operation that adds, releases, or re-reserves capacity must keep that sum exact."
    PRD §3.6: "unassigning clears the order's `route_id` and decreases the route's `reserved_gallons` by the order's `requested_gallons`, restoring capacity exactly."

    Design: Difficulty/compensating_invariant/truck_capacity_conserved_across_assign_unassign
    """
    base = fx.setup_account_with_passed_tank(tank_overrides={"capacity_gallons": 500,
                                                             "k_factor": 1500,
                                                             "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"])
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], order["id"], route["id"])
    mid = validate_success(api.get_route(route["id"], DISP))
    assert_route_reservation_conserved(mid, 200)

    validate_success(api.unassign_order(account["id"], order["id"], DISP))
    final = validate_success(api.get_route(route["id"], DISP))
    assert_route_reservation_conserved(final, 0)


def test_unassign_returns_order_to_created_and_clears_route(api):
    """PRD §3.6: "unassigning clears the order's `route_id` and decreases the route's `reserved_gallons` by the order's `requested_gallons`, restoring capacity exactly."

    Design: Difficulty/compensating_invariant/truck_capacity_conserved_across_assign_unassign
    """
    base = fx.setup_account_with_passed_tank(tank_overrides={"capacity_gallons": 500,
                                                             "k_factor": 1500,
                                                             "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"])
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], order["id"], route["id"])
    unassigned = validate_success(api.unassign_order(account["id"], order["id"], DISP))
    # The order side of the conserved transfer: back to CREATED with route_id cleared.
    assert unassigned["status"] == "CREATED"
    assert unassigned["route_id"] is None


def test_assign_reflects_reservation_in_same_response(api):
    """PRD §2.5: "A route's `reserved_gallons` is a conserved quantity: it is the running sum of `requested_gallons` over the orders currently holding a reservation on that route"
    PRD §3.6: "the route's `reserved_gallons` increases by this order's `requested_gallons`."

    Design: Corner/consistency_model/assign_reflects_reservation_in_same_response
    """
    base = fx.setup_account_with_passed_tank(tank_overrides={"capacity_gallons": 500,
                                                             "k_factor": 1500,
                                                             "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"])
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    fx.assign_order(account["id"], order["id"], route["id"])
    seen = validate_success(api.get_route(route["id"], DISP))
    assert seen["reserved_gallons"] == 200


# ---------------------------------------------------------------------------
# Corner: state_machines / errors — route + scheduling guards
# ---------------------------------------------------------------------------
def test_dispatch_empty_route_rejected(api):
    """PRD §3.5: "this requires the route to be in `PLANNING` (else `ERR_INVALID_STATE`) and to hold at least one `SCHEDULED` order (else `ERR_ROUTE_EMPTY`)."

    Design: Corner/state_machines/dispatch_empty_route_rejected
    """
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"], route_date="2026-03-02T00:00:00Z",
                            window_start="2026-03-02T09:00:00Z",
                            window_end="2026-03-02T12:00:00Z")
    resp = api.dispatch_route(truck["id"], route["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_EMPTY.value)


def test_unassign_dispatched_route_order_rejected(api):
    """PRD §3.6: "A dispatcher may unassign it, `SCHEDULED → CREATED`, which requires the order to be `SCHEDULED` (else `ERR_INVALID_STATE`) and, for the manual path, that the parent route is not already `DISPATCHED` (else `ERR_ROUTE_ALREADY_DISPATCHED`)"

    Design: Corner/errors/unassign_dispatched_route_order_rejected
    """
    s = fx.setup_order_on_dispatched_route(with_plan=False)
    resp = api.unassign_order(s["account"]["id"], s["order"]["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_ALREADY_DISPATCHED.value)


def test_decommission_tank_with_open_order_rejected(api):
    """PRD §3.3: "A tank may be decommissioned `IN_SERVICE → DECOMMISSIONED` by an account manager, but only when ... no `DeliveryOrder` for it sits in `SCHEDULED` or `HOLD` (else `ERR_TANK_HAS_OPEN_ORDERS`)."

    Design: Corner/errors/decommission_tank_with_open_order_rejected
    """
    s = fx.setup_order_scheduled_on_planning_route(with_plan=False)
    resp = api.decommission_tank(s["tank"]["id"], AM)
    validate_error(resp, ApiErrorId.ERR_TANK_HAS_OPEN_ORDERS.value)
