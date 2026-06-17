"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures produce
clear "Setup step failed" errors rather than confusing assertion failures.

Identity threading: the Customer role is entity-backed, so any ownership-gated
Customer call uses make_customer_headers(customer["id"]). DispatchOperator,
BillingClerk, and PlatformAdmin are opaque operators and use shared constants.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_container_model_payload,
    create_protection_plan_payload,
    create_depot_payload,
    create_depot_inventory_payload,
    create_crew_payload,
    create_truck_payload,
    create_customer_payload,
    create_rental_agreement_payload,
    create_delivery_job_payload,
    create_move_order_payload,
    create_packing_supply_order_payload,
    reserve_payload,
    payment_payload,
)
from .test_users import TEST_USERS, make_customer_headers

PA = TEST_USERS["platform_admin_headers"]
DO = TEST_USERS["dispatch_operator_headers"]
BC = TEST_USERS["billing_clerk_headers"]

DEFAULT_CLOCK = "2026-07-16T08:00:00Z"


# --- Tier 0: clock + atomic config creators -------------------------------

def set_clock(to_iso8601=DEFAULT_CLOCK):
    return get_success_data(api_client.set_clock(to_iso8601, PA))


def create_container_model(**overrides):
    return get_success_data(api_client.create_container_model(
        create_container_model_payload(**overrides), PA))


def create_protection_plan(**overrides):
    return get_success_data(api_client.create_protection_plan(
        create_protection_plan_payload(**overrides), PA))


def create_depot(**overrides):
    return get_success_data(api_client.create_depot(create_depot_payload(**overrides), PA))


def create_depot_inventory(depot_id, **overrides):
    return get_success_data(api_client.create_depot_inventory(
        create_depot_inventory_payload(depot_id, **overrides), PA))


def create_crew(depot_id, **overrides):
    return get_success_data(api_client.create_crew(create_crew_payload(depot_id, **overrides), PA))


def create_truck(depot_id, **overrides):
    return get_success_data(api_client.create_truck(create_truck_payload(depot_id, **overrides), PA))


def create_customer(**overrides):
    return get_success_data(api_client.create_customer(create_customer_payload(**overrides), PA))


def create_agreement(customer_id, depot_id, **overrides):
    """Create a QUOTED rental agreement (DispatchOperator). Returns the agreement dict."""
    return get_success_data(api_client.create_rental_agreement(
        create_rental_agreement_payload(customer_id, depot_id, **overrides), DO))


# --- Tier 1: catalog seeding ----------------------------------------------

def seed_world(size_code="C16", model_overrides=None, plan_overrides=None,
               depot_overrides=None, inventory_total_units=1, with_crew=True,
               with_truck=False, clock=DEFAULT_CLOCK, customer_email="customer@x.com"):
    """Seed a single-depot world and return a dict of created reference data.

    Keys: model, plan, depot, inventory, crew (optional), truck (optional), customer.
    """
    set_clock(clock)
    model = create_container_model(**{"size_code": size_code, **(model_overrides or {})})
    plan = create_protection_plan(**(plan_overrides or {}))
    depot = create_depot(**(depot_overrides or {}))
    inventory = create_depot_inventory(
        depot["id"], size_code=size_code, total_units=inventory_total_units)
    out = {
        "model": model, "plan": plan, "depot": depot,
        "inventory": inventory, "customer": create_customer(email=customer_email),
    }
    if with_crew:
        out["crew"] = create_crew(depot["id"])
    if with_truck:
        out["truck"] = create_truck(depot["id"])
    return out


# --- Tier 2: reservation ---------------------------------------------------

def reserve_unit(agreement):
    """Reserve a container against a QUOTED agreement (DispatchOperator). Returns the
    refreshed agreement dict after the reserve."""
    return get_success_data(api_client.reserve_agreement(
        agreement["id"], reserve_payload(agreement["version"]), DO))


def get_unit_for_agreement(agreement_id):
    """Return the first ContainerUnit drawn for the agreement."""
    units, _ = _list(api_client.list_agreement_container_units(agreement_id, DO))
    return units[0]


def create_quoted_then_reserved(world, agreement_overrides=None):
    """Create + reserve an agreement against a seeded world.

    Returns (agreement_after_reserve, unit).
    """
    ag = create_agreement(
        world["customer"]["id"], world["depot"]["id"],
        size_code=world["inventory"]["size_code"],
        protection_tier_code=world["plan"]["tier_code"],
        **(agreement_overrides or {}))
    ag = reserve_unit(ag)
    unit = get_unit_for_agreement(ag["id"])
    return ag, unit


# --- Tier 3: full delivery → ACTIVE lifecycle shortcut --------------------

def deliver_and_activate(world, agreement_overrides=None,
                         window_start="2026-07-16T09:00:00Z",
                         window_end="2026-07-16T11:00:00Z"):
    """Create → reserve → schedule INITIAL_DELIVERY → complete, landing the agreement
    in ACTIVE with an ON_SITE unit and the opening charges posted.

    Returns (agreement_after_activation, unit_after_activation).
    """
    ag, unit = create_quoted_then_reserved(world, agreement_overrides)
    job = get_success_data(api_client.create_delivery_job(
        create_delivery_job_payload(
            ag["id"], world["crew"]["id"], unit["id"],
            window_start=window_start, window_end=window_end),
        DO))
    get_success_data(api_client.complete_delivery_job(job["id"], DO))
    ag = get_success_data(api_client.get_rental_agreement(ag["id"], DO))
    unit = get_success_data(api_client.get_container_unit(unit["id"], DO))
    return ag, unit


def setup_active_agreement(size_code="C16", tier_code="NONE", declared_value_cents=0,
                           proration_method="CALENDAR_DAY", monthly_rate_cents=19900,
                           delivery_fee_cents=8900, footprint_sqft=160, plan_overrides=None,
                           inventory_total_units=1, with_truck=False,
                           service_radius_miles=50, clock=DEFAULT_CLOCK,
                           agreement_overrides=None):
    """Seed world + deliver to ACTIVE for the common single-agreement case.

    Returns (world, agreement, unit).
    """
    world = seed_world(
        size_code=size_code,
        model_overrides={
            "size_code": size_code, "monthly_rate_cents": monthly_rate_cents,
            "delivery_fee_cents": delivery_fee_cents, "footprint_sqft": footprint_sqft,
        },
        plan_overrides={"tier_code": tier_code, **(plan_overrides or {})},
        depot_overrides={"service_radius_miles": service_radius_miles},
        inventory_total_units=inventory_total_units,
        with_truck=with_truck, clock=clock,
    )
    ag, unit = deliver_and_activate(
        world,
        agreement_overrides={
            "declared_value_cents": declared_value_cents,
            "proration_method": proration_method,
            **(agreement_overrides or {}),
        })
    return world, ag, unit


# --- Tier 4: schedule a move on an ON_SITE unit ---------------------------

def schedule_move(world, agreement, unit, **move_overrides):
    """Schedule a MoveOrder for an ACTIVE agreement's ON_SITE unit (DispatchOperator).
    Requires the seeded world to carry a truck. Returns the move-order dict."""
    return get_success_data(api_client.create_move_order(
        create_move_order_payload(
            agreement["id"], world["truck"]["id"], unit["id"], world["depot"]["id"],
            **move_overrides),
        DO))


def dispatch_and_complete_move(move):
    """Dispatch then complete a SCHEDULED move (DispatchOperator), cascading the unit
    ON_SITE -> IN_TRANSIT -> ON_SITE and leaving the agreement free of open logistics.
    The MOVE charge posted at scheduling remains on the ledger. Returns the completed
    move-order dict."""
    get_success_data(api_client.dispatch_move_order(move["id"], DO))
    return get_success_data(api_client.complete_move_order(move["id"], DO))


# --- Tier 5: drive billing past the grace boundary ------------------------

def advance_clock_and_sweep(to_iso8601):
    """Set the clock then run a single late-fee sweep (BillingClerk)."""
    set_clock(to_iso8601)
    return get_success_data(api_client.run_late_sweep(BC))


def setup_past_due_agreement(clock=DEFAULT_CLOCK, sweep_clock="2026-07-22T12:00:00Z",
                             tier_code="NONE", **active_kwargs):
    """ACTIVE NONE-tier agreement delivered 2026-07-16, then swept at 6 days overdue so
    billing_status becomes PAST_DUE. Returns (world, agreement_after_sweep, unit)."""
    world, ag, unit = setup_active_agreement(tier_code=tier_code, clock=clock, **active_kwargs)
    advance_clock_and_sweep(sweep_clock)
    ag = get_success_data(api_client.get_rental_agreement(ag["id"], BC))
    return world, ag, unit


# --- Tier 6: pay off + request closeout + return unit ---------------------

def pay_full_balance(agreement, customer_id):
    """Read the current balance/version and pay it off in full (Customer)."""
    fresh = get_success_data(api_client.get_rental_agreement(
        agreement["id"], make_customer_headers(customer_id)))
    get_success_data(api_client.post_payment(
        agreement["id"],
        payment_payload(fresh["balance_due_cents"], fresh["version"]),
        make_customer_headers(customer_id)))
    return get_success_data(api_client.get_rental_agreement(
        agreement["id"], make_customer_headers(customer_id)))


def request_closeout(agreement, customer_id):
    return get_success_data(api_client.request_closeout(
        agreement["id"], make_customer_headers(customer_id)))


def return_unit(unit_id):
    return get_success_data(api_client.return_to_depot(unit_id, DO))


def setup_closing_unit_returned(tier_code="NONE", **active_kwargs):
    """ACTIVE agreement → pay to 0 → request-closeout (CLOSING) → return unit (RETURNED),
    leaving it ready for a successful close. Returns (world, agreement, unit)."""
    world, ag, unit = setup_active_agreement(tier_code=tier_code, **active_kwargs)
    cust_id = world["customer"]["id"]
    pay_full_balance(ag, cust_id)
    request_closeout(ag, cust_id)
    return_unit(unit["id"])
    ag = get_success_data(api_client.get_rental_agreement(ag["id"], BC))
    unit = get_success_data(api_client.get_container_unit(unit["id"], DO))
    return world, ag, unit


# --- internal helpers ------------------------------------------------------

def _list(response):
    """Return (data_list, meta) from a lenient-validated list response."""
    body = response.json()
    return body.get("data", []), body.get("meta", {})
