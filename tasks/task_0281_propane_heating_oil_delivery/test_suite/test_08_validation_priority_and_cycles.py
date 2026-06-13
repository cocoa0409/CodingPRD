"""Validation-priority conflicts, the cyclic hold/resume order flow, and the route
cancellation cascade.

Translates queue A (Difficulty) rules priority_pair_validation_conflict,
non_linear_state_machine (hold/resume cycle), and transitive_cascade (route cancel
cascade).
"""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    assign_order_payload, assert_route_reservation_conserved,
)
from test_helpers import fixtures as fx

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
INSP = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Difficulty: priority_pair_validation_conflict
# ---------------------------------------------------------------------------
def test_assign_safety_beats_capacity(api):
    """PRD §3.6: "In order: the order must be in `CREATED` (else `ERR_INVALID_STATE`); the target route must be in `PLANNING` (else `ERR_ROUTE_NOT_PLANNING`); the tank must be `IN_SERVICE` (else `ERR_TANK_NOT_IN_SERVICE`); the tank's most recent `SafetyInspection` must exist and have a `result` of `PASSED` (else `ERR_SAFETY_CHECK_REQUIRED`); and adding this order's `requested_gallons` must keep the route within the truck's limit ... (else `ERR_ROUTE_CAPACITY_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/assign_safety_beats_capacity
    """
    # Tank IN_SERVICE but NO inspection recorded -> safety gate fails; truck capacity
    # 100 with a 200-gal order -> capacity would also fail. Safety check is ordered
    # before capacity, so the safety error wins.
    account = fx.create_account(customer_name="Dual Dan")
    tank = fx.create_tank(account["id"], capacity_gallons=500, k_factor=1500,
                          current_gallons=100)
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=100)
    route = fx.create_route(truck["id"], route_date="2026-02-06T00:00:00Z",
                            window_start="2026-02-06T09:00:00Z",
                            window_end="2026-02-06T12:00:00Z")
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    resp = api.assign_order(account["id"], order["id"],
                            assign_order_payload(route["id"]), DISP)
    validate_error(resp, ApiErrorId.ERR_SAFETY_CHECK_REQUIRED.value)


def test_assign_capacity_fires_when_safety_satisfied(api):
    """PRD §3.6: "and adding this order's `requested_gallons` must keep the route within the truck's limit, meaning the route's existing `reserved_gallons` plus this order's `requested_gallons` must not exceed the truck's `daily_capacity_gallons` (else `ERR_ROUTE_CAPACITY_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/assign_safety_beats_capacity
    """
    # Same scenario but with safety satisfied (PASSED inspection). Only the capacity
    # check can now fail, isolating the lower-priority error.
    account = fx.create_account(customer_name="Cap Only Cam")
    tank = fx.create_tank(account["id"], capacity_gallons=500, k_factor=1500,
                          current_gallons=100)
    fx.record_inspection(tank["id"])
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=100)
    route = fx.create_route(truck["id"], route_date="2026-02-06T00:00:00Z",
                            window_start="2026-02-06T09:00:00Z",
                            window_end="2026-02-06T12:00:00Z")
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    resp = api.assign_order(account["id"], order["id"],
                            assign_order_payload(route["id"]), DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_CAPACITY_EXCEEDED.value)


def test_resume_state_beats_route_referential(api):
    """PRD §2.8: "the target resource must be in a state that permits the requested transition, else `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.6: "Resuming, `HOLD → SCHEDULED`, requires the order to be `HOLD` (else `ERR_INVALID_STATE`), the retained route to be back in `PLANNING` (else `ERR_ROUTE_NOT_PLANNING`), and the capacity to fit again"

    Design: Difficulty/priority_pair_validation_conflict/resume_state_beats_route_referential
    """
    # Order is CREATED (never put on HOLD) so the state check fails; the route is
    # CANCELLED so the route-referential check would also fail. State is ordered
    # before the route-phase check, so ERR_INVALID_STATE wins.
    account = fx.create_account(customer_name="State Steve")
    tank = fx.create_tank(account["id"], capacity_gallons=500, k_factor=1500,
                          current_gallons=100)
    fx.record_inspection(tank["id"])
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"], route_date="2026-02-07T00:00:00Z",
                            window_start="2026-02-07T09:00:00Z",
                            window_end="2026-02-07T12:00:00Z")
    validate_success(api.cancel_route(truck["id"], route["id"], DISP))
    order = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    resp = api.resume_order(account["id"], order["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_resume_route_referential_fires_when_state_satisfied(api):
    """PRD §3.6: "Resuming, `HOLD → SCHEDULED`, requires the order to be `HOLD` (else `ERR_INVALID_STATE`), the retained route to be back in `PLANNING` (else `ERR_ROUTE_NOT_PLANNING`), and the capacity to fit again"

    Design: Difficulty/priority_pair_validation_conflict/resume_state_beats_route_referential
    """
    # Order is properly on HOLD (state check passes) but its retained route has been
    # cancelled, isolating the lower-priority route-phase error.
    s = fx.setup_order_scheduled_on_planning_route(with_plan=False, requested_gallons=200)
    account, order, route, truck = s["account"], s["order"], s["route"], s["truck"]
    validate_success(api.hold_order(account["id"], order["id"], DISP))
    validate_success(api.cancel_route(truck["id"], route["id"], DISP))
    resp = api.resume_order(account["id"], order["id"], DISP)
    validate_error(resp, ApiErrorId.ERR_ROUTE_NOT_PLANNING.value)


# ---------------------------------------------------------------------------
# Difficulty: non_linear_state_machine — hold/resume cycle
# ---------------------------------------------------------------------------
def test_delivery_order_hold_resume_cycle(api):
    """PRD §3.6: "A dispatcher may instead place a scheduled order on hold, `SCHEDULED → HOLD`, permitted only from `SCHEDULED` (else `ERR_INVALID_STATE`); a held order releases its reservation (the route's `reserved_gallons` drops by the order's `requested_gallons`) but retains its `route_id` for later resumption."
    PRD §3.6: "on success the order returns to `SCHEDULED` and re-reserves its `requested_gallons`."

    Design: Difficulty/non_linear_state_machine/delivery_order_hold_resume_cycle
    """
    s = fx.setup_order_scheduled_on_planning_route(with_plan=False, requested_gallons=200)
    account, order, route = s["account"], s["order"], s["route"]
    held = validate_success(api.hold_order(account["id"], order["id"], DISP))
    assert held["status"] == "HOLD"

    resumed = validate_success(api.resume_order(account["id"], order["id"], DISP))
    assert resumed["status"] == "SCHEDULED"  # cycled back to a previously visited state
    route_after = validate_success(api.get_route(route["id"], DISP))
    # released to 0 on HOLD then re-reserved on resume -> back to 200.
    assert_route_reservation_conserved(route_after, 200)


def test_hold_releases_reservation_then_resume_rereserves(api):
    """PRD §3.6: "a held order releases its reservation (the route's `reserved_gallons` drops by the order's `requested_gallons`) but retains its `route_id` for later resumption."

    Design: Difficulty/non_linear_state_machine/delivery_order_hold_resume_cycle
    """
    s = fx.setup_order_scheduled_on_planning_route(with_plan=False, requested_gallons=200)
    account, order, route = s["account"], s["order"], s["route"]
    # Before hold the route reserves 200.
    before = validate_success(api.get_route(route["id"], DISP))
    assert_route_reservation_conserved(before, 200)
    validate_success(api.hold_order(account["id"], order["id"], DISP))
    on_hold = validate_success(api.get_route(route["id"], DISP))
    # On HOLD the reservation is released to 0.
    assert_route_reservation_conserved(on_hold, 0)


# ---------------------------------------------------------------------------
# Difficulty: transitive_cascade — route cancel reverts orders, releases capacity
# ---------------------------------------------------------------------------
def test_route_cancel_cascade_revert_orders_release_capacity(api):
    """PRD §3.5: "Cancelling from `PLANNING` (`PLANNING → CANCELLED`) requires the route to be in `PLANNING` and, as a cascade, reverts every `DeliveryOrder` whose `route_id` is this route and whose status is `SCHEDULED` back to `CREATED`; each reverted order then clears its `route_id`, and the truck's reserved capacity for that `route_date` is released so the route's `reserved_gallons` is recomputed to 0."

    Design: Difficulty/transitive_cascade/route_cancel_cascade_revert_orders_release_capacity
    """
    base = fx.setup_account_with_passed_tank(tank_overrides={"capacity_gallons": 800,
                                                             "k_factor": 1500,
                                                             "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"], route_date="2026-02-05T00:00:00Z",
                            window_start="2026-02-05T09:00:00Z",
                            window_end="2026-02-05T12:00:00Z")
    o1 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    o2 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=150)
    fx.assign_order(account["id"], o1["id"], route["id"])
    fx.assign_order(account["id"], o2["id"], route["id"])  # reserved 350

    cancelled = validate_success(api.cancel_route(truck["id"], route["id"], DISP))
    assert cancelled["status"] == "CANCELLED"
    assert_route_reservation_conserved(cancelled, 0)  # released from 350
    o1_after = validate_success(api.get_order(o1["id"], DISP))
    assert o1_after["status"] == "CREATED"  # reverted
    assert o1_after["route_id"] is None  # route_id cleared


def test_route_cancel_reverts_every_scheduled_order(api):
    """PRD §3.5: "reverts every `DeliveryOrder` whose `route_id` is this route and whose status is `SCHEDULED` back to `CREATED`; each reverted order then clears its `route_id"

    Design: Difficulty/transitive_cascade/route_cancel_cascade_revert_orders_release_capacity
    """
    base = fx.setup_account_with_passed_tank(tank_overrides={"capacity_gallons": 800,
                                                             "k_factor": 1500,
                                                             "current_gallons": 100})
    account, tank = base["account"], base["tank"]
    truck = fx.create_truck(region_code="NE_01", daily_capacity_gallons=1000)
    route = fx.create_route(truck["id"], route_date="2026-02-05T00:00:00Z",
                            window_start="2026-02-05T09:00:00Z",
                            window_end="2026-02-05T12:00:00Z")
    o1 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=200)
    o2 = fx.create_will_call_order(account["id"], tank["id"], requested_gallons=150)
    fx.assign_order(account["id"], o1["id"], route["id"])
    fx.assign_order(account["id"], o2["id"], route["id"])
    validate_success(api.cancel_route(truck["id"], route["id"], DISP))

    # The SECOND scheduled order is also reverted and detached by the cascade.
    o2_after = validate_success(api.get_order(o2["id"], DISP))
    assert o2_after["status"] == "CREATED"
    assert o2_after["route_id"] is None
