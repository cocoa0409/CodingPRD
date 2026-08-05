"""Validation gates, cross-entity state dependencies, and priority-ordered conflicts.

Queue A: priority_pair_validation_conflict (state>fiscal, safety>temporal),
cross_entity_state_dependency (order->vehicle, route->truck).
Queue B: fleet fuel-type/addon/budget, zone mismatch, compartment fuel, membership paused,
non-fleet customer, restock overfill.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    make_member_headers, make_fleet_manager_headers,
    setup_fleet_two_vehicles, setup_vehicle_with_scheduled_order,
    setup_planning_route_truck_maintenance, get_order, get_route,
    post_fuel_price, new_customer, new_vehicle, new_membership, new_order,
    new_fleet_account, new_truck, new_compartment, new_route,
    TEST_USERS,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]
ADMIN = TEST_USERS["admin_headers"]


# ─── Queue A: priority_pair_validation_conflict ─────────────────────────────

def test_suspended_vehicle_state_beats_budget_exceeded(api):
    """PRD §2.8: "Requests are validated in a fixed priority order, and the first failing
    check determines the error returned."
    PRD §2.8: "A check at a lower priority is only reached once every higher-priority check
    has passed."
    PRD §3.4: "the target vehicle must be `ACTIVE` — an order on a `SUSPENDED` vehicle is
    rejected with `ERR_VEHICLE_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/state_suspended_vehicle_beats_fiscal_budget_exceeded
    """
    ctx = setup_fleet_two_vehicles(target_cap_cents=100, other_cap_cents=100000,
                                   suspend_target=True)
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_a"],
         "fleet_account_id": ctx["fleet_account_id"], "zone": "ZONE_A",
         "delivery_address": "1 Fleet Rd", "requested_gallons": 10,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_fleet_manager_headers(ctx["customer_id"]))
    validate_error(res, "ERR_VEHICLE_SUSPENDED", expected_status=409)


def test_suspended_vehicle_wins_never_returns_budget_error(api):
    """PRD §2.8: "A check at a lower priority is only reached once every higher-priority
    check has passed."
    PRD §3.4: "an order on a `SUSPENDED` vehicle is rejected with `ERR_VEHICLE_SUSPENDED`."

    Design: Difficulty/priority_pair_validation_conflict/state_suspended_vehicle_beats_fiscal_budget_exceeded
    """
    ctx = setup_fleet_two_vehicles(target_cap_cents=100, other_cap_cents=100000,
                                   suspend_target=True)
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_a"],
         "fleet_account_id": ctx["fleet_account_id"], "zone": "ZONE_A",
         "delivery_address": "1 Fleet Rd", "requested_gallons": 10,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_fleet_manager_headers(ctx["customer_id"]))
    body = res.json()["data"]
    assert body["error_id"] == "ERR_VEHICLE_SUSPENDED"
    assert body["error_id"] != "ERR_VEHICLE_BUDGET_EXCEEDED"


def test_tank_overfill_safety_beats_window_conflict(api):
    """PRD §2.8: "(6) safety limits on gallons; (7) temporal-overlap rules;"
    PRD §2.8: "A check at a lower priority is only reached once every higher-priority check
    has passed."
    PRD §3.4: "a request that exceeds that headroom is rejected with
    `ERR_EXCEEDS_TANK_CAPACITY`."

    Design: Difficulty/priority_pair_validation_conflict/safety_tank_overfill_beats_temporal_window_conflict
    """
    ctx = setup_vehicle_with_scheduled_order(
        tank_capacity_gallons=15, current_fuel_level_gallons=10, requested_gallons=5,
        window_start="2026-05-02T09:00:00Z", window_end="2026-05-02T10:00:00Z")
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_id"], "zone": "ZONE_A",
         "delivery_address": "3 First Ave", "requested_gallons": 9,
         "delivery_window_start": "2026-05-02T10:15:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(ctx["customer_id"]))
    validate_error(res, "ERR_EXCEEDS_TANK_CAPACITY", expected_status=422)


def test_tank_overfill_wins_never_returns_window_conflict(api):
    """PRD §2.8: "A check at a lower priority is only reached once every higher-priority
    check has passed."
    PRD §3.4: "a request that exceeds that headroom is rejected with
    `ERR_EXCEEDS_TANK_CAPACITY`."

    Design: Difficulty/priority_pair_validation_conflict/safety_tank_overfill_beats_temporal_window_conflict
    """
    ctx = setup_vehicle_with_scheduled_order(
        tank_capacity_gallons=15, current_fuel_level_gallons=10, requested_gallons=5,
        window_start="2026-05-02T09:00:00Z", window_end="2026-05-02T10:00:00Z")
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_id"], "zone": "ZONE_A",
         "delivery_address": "3 First Ave", "requested_gallons": 9,
         "delivery_window_start": "2026-05-02T10:15:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(ctx["customer_id"]))
    body = res.json()["data"]
    assert body["error_id"] == "ERR_EXCEEDS_TANK_CAPACITY"
    assert body["error_id"] != "ERR_VEHICLE_WINDOW_CONFLICT"


# ─── Queue A: cross_entity_state_dependency ─────────────────────────────────

def test_order_create_blocked_on_suspended_vehicle(api):
    """PRD §3.4: "For state validity, the target vehicle must be `ACTIVE` — an order on a
    `SUSPENDED` vehicle is rejected with `ERR_VEHICLE_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_vehicle_active
    """
    ctx = setup_fleet_two_vehicles(target_cap_cents=100000, other_cap_cents=100000,
                                   suspend_target=True)
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_a"],
         "fleet_account_id": ctx["fleet_account_id"], "zone": "ZONE_A",
         "delivery_address": "1 Fleet Rd", "requested_gallons": 10,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_fleet_manager_headers(ctx["customer_id"]))
    validate_error(res, "ERR_VEHICLE_SUSPENDED", expected_status=409)


def test_order_create_allowed_on_active_sibling_vehicle(api):
    """PRD §3.4: "For state validity, the target vehicle must be `ACTIVE` — an order on a
    `SUSPENDED` vehicle is rejected with `ERR_VEHICLE_SUSPENDED`."

    Design: Difficulty/cross_entity_state_dependency/order_create_requires_vehicle_active
    """
    ctx = setup_fleet_two_vehicles(target_cap_cents=100000, other_cap_cents=100000,
                                   suspend_target=True)
    # The still-ACTIVE sibling vehicle accepts an order — the block is specific to the
    # SUSPENDED vehicle, not a blanket account-level denial.
    res = api.create_order(
        {"customer_id": ctx["customer_id"], "vehicle_id": ctx["vehicle_b"],
         "fleet_account_id": ctx["fleet_account_id"], "zone": "ZONE_A",
         "delivery_address": "2 Fleet Rd", "requested_gallons": 10,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_fleet_manager_headers(ctx["customer_id"]))
    order = validate_success(res, 201)
    assert order["status"] == "SCHEDULED"


def test_route_dispatch_blocked_when_truck_in_maintenance(api):
    """PRD §3.5: "A `Dispatcher` dispatches a route that is in `PLANNING`; the route's truck
    must be `AVAILABLE`, or the dispatch is rejected with `ERR_TRUCK_UNAVAILABLE`, and the
    route must carry at least one stop (`stop_count` of 1 or more)."

    Design: Difficulty/cross_entity_state_dependency/route_dispatch_requires_truck_available
    """
    ctx = setup_planning_route_truck_maintenance()
    res = api.dispatch_route(ctx["route_id"], DISPATCHER)
    validate_error(res, "ERR_TRUCK_UNAVAILABLE", expected_status=409)


def test_route_stays_planning_when_dispatch_blocked(api):
    """PRD §3.5: "the route's truck must be `AVAILABLE`, or the dispatch is rejected with
    `ERR_TRUCK_UNAVAILABLE`, and the route must carry at least one stop (`stop_count` of 1
    or more)."

    Design: Difficulty/cross_entity_state_dependency/route_dispatch_requires_truck_available
    """
    ctx = setup_planning_route_truck_maintenance()
    api.dispatch_route(ctx["route_id"], DISPATCHER)
    assert get_route(ctx["route_id"])["status"] == "PLANNING"


# ─── Queue B: validations ───────────────────────────────────────────────────

def test_fleet_order_fuel_type_not_allowed(api):
    """PRD §3.4: "a fleet order's `fuel_type` (the grade copied from the vehicle) must
    appear in the fleet account's `allowed_fuel_types`, or the order is rejected with
    `ERR_FUEL_TYPE_NOT_ALLOWED`;"

    Design: Corner/validations/fleet_order_fuel_type_not_allowed
    """
    post_fuel_price(fuel_type="PREMIUM", price_per_gallon_cents=489)
    cust = new_customer(customer_type="FLEET", name="PremFleet", email="ops@premfleet.com")
    fa = new_fleet_account(cust["id"], allowed_fuel_types=["REGULAR"])
    veh = new_vehicle(cust["id"], fuel_type="PREMIUM", fleet_account_id=fa["id"],
                      monthly_spend_cap_cents=100000, make_model="Golf R", as_fleet=True)
    res = api.create_order(
        {"customer_id": cust["id"], "vehicle_id": veh["id"], "fleet_account_id": fa["id"],
         "zone": "ZONE_A", "delivery_address": "Prem St", "requested_gallons": 10,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_fleet_manager_headers(cust["id"]))
    validate_error(res, "ERR_FUEL_TYPE_NOT_ALLOWED", expected_status=422)


def test_assign_route_zone_mismatch_rejected(api):
    """PRD §3.5: "The route's `zone` must equal the order's `zone`, or the assignment is
    rejected with `ERR_ROUTE_ZONE_MISMATCH`."

    Design: Corner/validations/assign_route_zone_mismatch
    """
    post_fuel_price()
    cust = new_customer(name="Zoe", email="zoe@x.com")
    veh = new_vehicle(cust["id"], make_model="ID.4")
    truck = new_truck(plate="TRK-ZB", home_zone="ZONE_B")
    new_compartment(truck["id"])
    route = new_route(truck["id"], assigned_driver_id="driver-zb", zone="ZONE_B")
    order = new_order(cust["id"], veh["id"], zone="ZONE_A", requested_gallons=5,
                      delivery_address="Zone St",
                      delivery_window_start="2026-05-02T09:00:00Z",
                      delivery_window_end="2026-05-02T10:00:00Z")
    res = api.assign_route(order["id"], {"route_id": route["id"]}, DISPATCHER)
    validate_error(res, "ERR_ROUTE_ZONE_MISMATCH", expected_status=422)


def test_assign_route_insufficient_compartment_fuel(api):
    """PRD §3.5: "it must have a compartment of the order's `fuel_type` whose
    `gallons_available` is at least the order's `requested_gallons`; if no matching
    compartment exists or the matching compartment lacks sufficient available gallons, the
    assignment is rejected with `ERR_INSUFFICIENT_COMPARTMENT_FUEL`."

    Design: Corner/validations/insufficient_compartment_fuel_rejected
    """
    post_fuel_price()
    cust = new_customer(name="Ann", email="ann@x.com")
    veh = new_vehicle(cust["id"], tank_capacity_gallons=100, make_model="Atlas")
    truck = new_truck(plate="TRK-LO")
    new_compartment(truck["id"], gallons_onboard=30)
    route = new_route(truck["id"], assigned_driver_id="driver-lo")
    order = new_order(cust["id"], veh["id"], requested_gallons=50, delivery_address="Low St")
    res = api.assign_route(order["id"], {"route_id": route["id"]}, DISPATCHER)
    validate_error(res, "ERR_INSUFFICIENT_COMPARTMENT_FUEL", expected_status=409)


def test_fleet_budget_exceeded_rejected(api):
    """PRD §3.4: "for a fleet order, the estimated total must not push the fleet account's
    settled-plus-committed budget above its `monthly_budget_cap_cents`, or it is rejected
    with `ERR_FLEET_BUDGET_EXCEEDED`."

    Design: Corner/validations/fleet_budget_exceeded_rejected
    """
    post_fuel_price(fuel_type="DIESEL", price_per_gallon_cents=459)
    cust = new_customer(customer_type="FLEET", name="TinyFleet", email="ops@tinyfleet.com")
    fa = new_fleet_account(cust["id"], monthly_budget_cap_cents=100, allowed_fuel_types=["DIESEL"])
    veh = new_vehicle(cust["id"], fuel_type="DIESEL", tank_capacity_gallons=100,
                      fleet_account_id=fa["id"], monthly_spend_cap_cents=100000,
                      make_model="Crafter", as_fleet=True)
    res = api.create_order(
        {"customer_id": cust["id"], "vehicle_id": veh["id"], "fleet_account_id": fa["id"],
         "zone": "ZONE_A", "delivery_address": "Big St", "requested_gallons": 10,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_fleet_manager_headers(cust["id"]))
    validate_error(res, "ERR_FLEET_BUDGET_EXCEEDED", expected_status=402)


def test_member_order_while_membership_paused_rejected(api):
    """PRD §3.4: "For a member order, the referenced membership must be `ACTIVE`; if it is
    `PAUSED`, `PAST_DUE`, or `CANCELLED`, the order is rejected with
    `ERR_MEMBERSHIP_NOT_ACTIVE`."

    Design: Corner/validations/member_order_while_membership_paused_rejected
    """
    post_fuel_price()
    cust = new_customer(name="Bea", email="bea@x.com")
    mem = new_membership(cust["id"], included_deliveries=5)
    veh = new_vehicle(cust["id"], make_model="e-Up")
    get_success_data(api.pause_membership(mem["id"], make_member_headers(cust["id"])))
    res = api.create_order(
        {"customer_id": cust["id"], "vehicle_id": veh["id"], "membership_id": mem["id"],
         "zone": "ZONE_A", "delivery_address": "Paused St", "requested_gallons": 8,
         "delivery_window_start": "2026-05-02T09:00:00Z",
         "delivery_window_end": "2026-05-02T11:00:00Z"},
        make_member_headers(cust["id"]))
    validate_error(res, "ERR_MEMBERSHIP_NOT_ACTIVE", expected_status=409)


def test_fleet_account_for_non_fleet_customer_rejected(api):
    """PRD §3.1: "the referenced customer's `customer_type` must be `FLEET`, and an attempt
    to open a fleet account for a non-fleet customer is rejected with
    `ERR_CUSTOMER_NOT_FLEET`."

    Design: Corner/validations/fleet_account_create_non_fleet_customer_rejected
    """
    cust = new_customer(customer_type="INDIVIDUAL", name="Cal", email="cal@x.com")
    res = api.create_fleet_account(
        {"customer_id": cust["id"], "monthly_budget_cap_cents": 100000,
         "allowed_fuel_types": ["REGULAR"], "allowed_addons": []},
        make_fleet_manager_headers(cust["id"]))
    validate_error(res, "ERR_CUSTOMER_NOT_FLEET", expected_status=422)


def test_restock_overfill_rejected(api):
    """PRD §3.3: "A restock that would push `gallons_onboard` above the compartment's
    `gallons_capacity` is rejected with `ERR_COMPARTMENT_OVERFILL`."

    Design: Corner/validations/restock_overfill_rejected
    """
    truck = new_truck(plate="TRK-OF")
    comp = new_compartment(truck["id"], gallons_capacity=200, gallons_onboard=50)
    res = api.restock_truck(truck["id"], {"compartment_id": comp["id"], "gallons": 300}, ADMIN)
    validate_error(res, "ERR_COMPARTMENT_OVERFILL", expected_status=409)
