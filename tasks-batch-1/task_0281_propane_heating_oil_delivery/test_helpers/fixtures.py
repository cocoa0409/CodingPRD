"""Composite setup helpers.

Every test runs against an empty database (the harness restarts the server before
each test), so every fixture builds its preconditions from scratch using only
PRD-declared endpoints. Fixtures use get_success_data() (lenient) internally so
setup failures surface as clear "Setup failed" errors.

Identity threading: the Customer role is entity_backed:Account, so any
ownership-gated Customer call uses make_customer_headers(account_id). All other
roles are opaque and use the shared TEST_USERS constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS, make_customer_headers
from . import factories as f

AM = TEST_USERS["account_manager_headers"]
DISP = TEST_USERS["dispatcher_headers"]
DRIVER = TEST_USERS["driver_headers"]
INSP = TEST_USERS["inspector_headers"]


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def set_clock(to_iso8601, headers=None):
    """Set the logical system clock (PRD §2.10). Returns nothing useful."""
    return get_success_data(api_client.set_clock(to_iso8601, headers or DISP))


# ---------------------------------------------------------------------------
# Tier 1: simple entity creation
# ---------------------------------------------------------------------------
def create_account(region_code="NE_01", fuel_type="PROPANE",
                   customer_name="Test Customer", **overrides) -> dict:
    """Create an Account; returns the account resource (ACTIVE, version 1)."""
    payload = f.create_account_payload(
        customer_name=customer_name, region_code=region_code,
        fuel_type=fuel_type, **overrides)
    return get_success_data(api_client.create_account(payload, AM))


def create_tank(account_id, **overrides) -> dict:
    """Create a Tank under an account; returns the tank resource."""
    payload = f.create_tank_payload(**overrides)
    return get_success_data(api_client.create_tank(account_id, payload, AM))


def create_truck(region_code="NE_01", daily_capacity_gallons=1000, **overrides) -> dict:
    """Create a Truck; returns the truck resource."""
    payload = f.create_truck_payload(
        region_code=region_code, daily_capacity_gallons=daily_capacity_gallons, **overrides)
    return get_success_data(api_client.create_truck(payload, DISP))


def create_route(truck_id, **overrides) -> dict:
    """Create a PLANNING route on a truck; returns the route resource."""
    payload = f.create_route_payload(**overrides)
    return get_success_data(api_client.create_route(truck_id, payload, DISP))


def create_market_price(region_code="NE_01", fuel_type="PROPANE",
                        market_price_cents_per_gallon=350) -> dict:
    """Publish an ACTIVE market quote; returns the quote resource."""
    payload = f.create_market_price_payload(
        region_code=region_code, fuel_type=fuel_type,
        market_price_cents_per_gallon=market_price_cents_per_gallon)
    return get_success_data(api_client.create_market_price(payload, AM))


def record_inspection(tank_id, result="PASSED", inspected_at="2026-01-01T00:00:00Z") -> dict:
    """Record a safety inspection on a tank; returns the inspection resource."""
    payload = f.create_inspection_payload(result=result, inspected_at=inspected_at)
    return get_success_data(api_client.create_inspection(tank_id, payload, INSP))


def record_reading(tank_id, reading_gallons, read_at) -> dict:
    """Record a tank-monitor reading; returns the reading resource."""
    payload = f.create_reading_payload(reading_gallons=reading_gallons, read_at=read_at)
    return get_success_data(api_client.create_reading(tank_id, payload, DRIVER))


def record_degree_day(region_code, reading_date, heating_degree_days) -> dict:
    """Record a regional HDD total; returns the reading resource."""
    payload = f.create_degree_day_reading_payload(
        region_code=region_code, reading_date=reading_date,
        heating_degree_days=heating_degree_days)
    return get_success_data(api_client.create_degree_day_reading(payload, DISP))


# ---------------------------------------------------------------------------
# Tier 1: price-plan progression
# ---------------------------------------------------------------------------
def create_active_fixed_plan(account_id, locked_price_cents_per_gallon=300) -> dict:
    """Draft a FIXED plan and activate it. Returns the activated plan."""
    plan = get_success_data(api_client.create_price_plan(
        account_id,
        f.create_price_plan_payload(plan_type="FIXED",
                                    locked_price_cents_per_gallon=locked_price_cents_per_gallon),
        AM))
    return get_success_data(api_client.activate_price_plan(account_id, plan["id"], AM))


def create_active_cap_plan(account_id, cap_price_cents_per_gallon=300) -> dict:
    """Draft a CAP plan and activate it (requires an ACTIVE MarketPrice). Returns plan."""
    plan = get_success_data(api_client.create_price_plan(
        account_id,
        f.create_price_plan_payload(plan_type="CAP",
                                    cap_price_cents_per_gallon=cap_price_cents_per_gallon),
        AM))
    return get_success_data(api_client.activate_price_plan(account_id, plan["id"], AM))


def create_active_market_plan(account_id) -> dict:
    """Draft a MARKET plan and activate it (requires an ACTIVE MarketPrice). Returns plan."""
    plan = get_success_data(api_client.create_price_plan(
        account_id, f.create_price_plan_payload(plan_type="MARKET"), AM))
    return get_success_data(api_client.activate_price_plan(account_id, plan["id"], AM))


# ---------------------------------------------------------------------------
# Tier 2: account + tank base scenarios
# ---------------------------------------------------------------------------
def setup_account_with_passed_tank(region_code="NE_01", fuel_type="PROPANE",
                                   tank_overrides=None) -> dict:
    """Account + IN_SERVICE tank with a most-recent PASSED inspection.

    Returns {account, tank}. No price plan, no truck/route.
    """
    account = create_account(region_code=region_code, fuel_type=fuel_type)
    tank = create_tank(account["id"], **(tank_overrides or {"current_gallons": 100}))
    record_inspection(tank["id"])
    return {"account": account, "tank": tank}


def setup_account_plan_passed_tank(plan_type="FIXED", locked_price=300,
                                   cap_price=300, region_code="NE_01",
                                   fuel_type="PROPANE", market_price=350,
                                   tank_overrides=None) -> dict:
    """Account + ACTIVE price plan + PASSED tank.

    For MARKET/CAP plans an ACTIVE MarketPrice for (region, fuel) is published
    first. Returns {account, plan, tank}.
    """
    if plan_type in ("MARKET", "CAP"):
        create_market_price(region_code=region_code, fuel_type=fuel_type,
                            market_price_cents_per_gallon=market_price)
    account = create_account(region_code=region_code, fuel_type=fuel_type)
    if plan_type == "FIXED":
        plan = create_active_fixed_plan(account["id"], locked_price_cents_per_gallon=locked_price)
    elif plan_type == "CAP":
        plan = create_active_cap_plan(account["id"], cap_price_cents_per_gallon=cap_price)
    else:
        plan = create_active_market_plan(account["id"])
    tank = create_tank(account["id"], **(tank_overrides or {"current_gallons": 100}))
    record_inspection(tank["id"])
    return {"account": account, "plan": plan, "tank": tank}


# ---------------------------------------------------------------------------
# Tier 3: order lifecycle shortcuts
# ---------------------------------------------------------------------------
def create_will_call_order(account_id, tank_id, requested_gallons=200,
                           priority=None) -> dict:
    """Create a will-call DeliveryOrder (origin WILL_CALL, status CREATED)."""
    overrides = {}
    if priority is not None:
        overrides["priority"] = priority
    payload = f.create_order_payload(tank_id, requested_gallons=requested_gallons, **overrides)
    return get_success_data(api_client.create_order(account_id, payload, DISP))


def assign_order(account_id, order_id, route_id) -> dict:
    """Assign a CREATED order to a PLANNING route; returns the SCHEDULED order."""
    return get_success_data(api_client.assign_order(
        account_id, order_id, f.assign_order_payload(route_id), DISP))


def dispatch_route(truck_id, route_id) -> dict:
    """Dispatch a PLANNING route (must hold >=1 SCHEDULED order). Returns the route."""
    return get_success_data(api_client.dispatch_route(truck_id, route_id, DISP))


def get_account_version(account_id) -> int:
    """Read the account's current version (for the OCC check on deliver/reverse)."""
    return get_success_data(api_client.get_account(account_id, AM))["version"]


def setup_order_scheduled_on_planning_route(plan_type="FIXED", locked_price=300,
                                            requested_gallons=200, priority=None,
                                            truck_overrides=None, tank_overrides=None,
                                            with_plan=True, region_code="NE_01",
                                            fuel_type="PROPANE", market_price=350,
                                            cap_price=300) -> dict:
    """Account (+ optional ACTIVE plan) + PASSED tank + truck + PLANNING route +
    one order SCHEDULED on that route.

    Returns {account, plan, tank, truck, route, order}. plan is None when
    with_plan is False.
    """
    if with_plan:
        base = setup_account_plan_passed_tank(
            plan_type=plan_type, locked_price=locked_price, cap_price=cap_price,
            region_code=region_code, fuel_type=fuel_type, market_price=market_price,
            tank_overrides=tank_overrides)
        plan = base["plan"]
    else:
        base = setup_account_with_passed_tank(region_code=region_code, fuel_type=fuel_type,
                                              tank_overrides=tank_overrides)
        plan = None
    account, tank = base["account"], base["tank"]
    truck = create_truck(region_code=region_code, **(truck_overrides or {}))
    route = create_route(truck["id"])
    order = create_will_call_order(account["id"], tank["id"],
                                   requested_gallons=requested_gallons, priority=priority)
    assign_order(account["id"], order["id"], route["id"])
    return {"account": account, "plan": plan, "tank": tank,
            "truck": truck, "route": route, "order": order}


def setup_order_on_dispatched_route(plan_type="FIXED", locked_price=300,
                                    requested_gallons=200, priority=None,
                                    tank_overrides=None, with_plan=True,
                                    region_code="NE_01",
                                    fuel_type="PROPANE", market_price=350,
                                    cap_price=300) -> dict:
    """Full setup through a DISPATCHED route holding one SCHEDULED order, ready
    to deliver. Returns {account, plan, tank, truck, route, order}. plan is None
    when with_plan is False.
    """
    s = setup_order_scheduled_on_planning_route(
        plan_type=plan_type, locked_price=locked_price,
        requested_gallons=requested_gallons, priority=priority,
        tank_overrides=tank_overrides, with_plan=with_plan, region_code=region_code,
        fuel_type=fuel_type, market_price=market_price, cap_price=cap_price)
    dispatch_route(s["truck"]["id"], s["route"]["id"])
    return s


def deliver_order(account_id, order_id, delivered_gallons, expected_account_version=None) -> dict:
    """Deliver a SCHEDULED order on a DISPATCHED route. Reads the live account
    version when expected_account_version is not supplied. Returns the DELIVERED order.
    """
    if expected_account_version is None:
        expected_account_version = get_account_version(account_id)
    payload = f.deliver_order_payload(delivered_gallons, expected_account_version)
    return get_success_data(api_client.deliver_order(account_id, order_id, payload, DRIVER))


def deliver_scheduled_order(setup: dict, delivered_gallons) -> dict:
    """Convenience: deliver the order from a setup_order_on_dispatched_route() result.
    Returns the DELIVERED order resource."""
    return deliver_order(setup["account"]["id"], setup["order"]["id"], delivered_gallons)


# ---------------------------------------------------------------------------
# Tier 4: budget-pay scenarios
# ---------------------------------------------------------------------------
def create_budget_plan(account_id, estimated_annual_gallons=1200,
                       estimated_price_cents_per_gallon=300,
                       plan_year_start="2026-01-01T00:00:00Z") -> dict:
    """Enroll an account in budget pay; returns the ACTIVE plan."""
    payload = f.create_budget_plan_payload(
        plan_year_start=plan_year_start,
        estimated_annual_gallons=estimated_annual_gallons,
        estimated_price_cents_per_gallon=estimated_price_cents_per_gallon)
    return get_success_data(api_client.create_budget_plan(account_id, payload, AM))


def post_installments(account_id, budget_plan_id, n) -> dict:
    """Post n monthly installments; returns the budget plan after the last post."""
    result = None
    for _ in range(n):
        result = get_success_data(
            api_client.post_installment(account_id, budget_plan_id, AM))
    return result


# ---------------------------------------------------------------------------
# Tier 5: reorder-projection targeting
# ---------------------------------------------------------------------------
def setup_tank_for_projection(region_code="NE_01", fuel_type="PROPANE",
                              created_clock="2026-01-01T00:00:00Z",
                              tank_overrides=None) -> dict:
    """Set the clock to created_clock, then create an account + tank so the tank's
    creation-time baseline anchor is created_clock. Returns {account, tank}.

    Caller advances the clock and records degree-day/monitor readings as needed.
    """
    set_clock(created_clock)
    account = create_account(region_code=region_code, fuel_type=fuel_type)
    tank = create_tank(account["id"], **(tank_overrides or {}))
    return {"account": account, "tank": tank}


def evaluate_reorder(tank_id) -> dict:
    """Recompute reorder_status at the current clock; returns the tank."""
    return get_success_data(api_client.evaluate_reorder(tank_id, DISP))


def get_route(route_id) -> dict:
    """Read a route; returns the route resource."""
    return get_success_data(api_client.get_route(route_id, DISP))


def get_tank(tank_id) -> dict:
    """Read a tank; returns the tank resource."""
    return get_success_data(api_client.get_tank(tank_id, DISP))


def get_budget_plan(budget_plan_id) -> dict:
    """Read a budget plan; returns the resource."""
    return get_success_data(api_client.get_budget_plan(budget_plan_id, AM))


def create_lease(tank_id, monthly_rent_cents=5000,
                 lease_start="2026-01-01T00:00:00Z",
                 lease_end="2026-04-01T00:00:00Z") -> dict:
    """Create an ACTIVE tank lease; returns the lease resource."""
    payload = f.create_lease_payload(
        monthly_rent_cents=monthly_rent_cents,
        lease_start=lease_start, lease_end=lease_end)
    return get_success_data(api_client.create_lease(tank_id, payload, AM))
