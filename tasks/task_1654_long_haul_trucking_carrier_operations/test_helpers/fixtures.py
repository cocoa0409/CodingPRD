"""Composite setup helpers — multi-step PRD workflow preambles.

Fixtures use get_success_data() internally so a setup failure surfaces as a
clear "Setup step failed" assertion instead of a confusing downstream error.

Identity threading: Driver-role writes (duty events, check calls, fuel
purchases) always use make_driver_headers(driver["id"]) — never the shared
fallback constant — because those endpoints are ownership-gated (PRD §2.1).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_accessorial_payload,
    create_check_call_payload,
    create_customer_payload,
    create_driver_payload,
    create_duty_event_payload,
    create_fuel_purchase_payload,
    create_lane_payload,
    create_load_payload,
    create_safety_event_payload,
    create_settlement_payload,
    create_state_fuel_rate_payload,
    create_tractor_payload,
    create_trip_payload,
)
from .test_users import TEST_USERS, make_driver_headers, make_payroll_clerk_headers

FLEET_ADMIN = TEST_USERS["fleet_admin_headers"]
LOAD_PLANNER = TEST_USERS["load_planner_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
SAFETY_OFFICER = TEST_USERS["safety_officer_headers"]
PAYROLL_CLERK = TEST_USERS["payroll_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1: single-entity creation helpers
# ---------------------------------------------------------------------------

def set_clock(to_iso8601: str = DEFAULT_CLOCK):
    """Install the logical clock (PRD §2.4; FleetAdmin-only)."""
    return get_success_data(
        api_client.set_clock({"to_iso8601": to_iso8601}, FLEET_ADMIN))


def create_driver(**overrides):
    payload = create_driver_payload(**overrides)
    # Pay-config completeness is per-model (PRD §3.1): a PERCENTAGE driver is
    # registered with pay_percentage_bp and no mileage rate.
    if payload.get("pay_model") == "PERCENTAGE":
        payload.pop("pay_rate_cents_per_mile", None)
    return get_success_data(api_client.create_driver(payload, FLEET_ADMIN))


def create_tractor(**overrides):
    return get_success_data(
        api_client.create_tractor(create_tractor_payload(**overrides), FLEET_ADMIN))


def create_customer(name: str = "Acme Foods"):
    return get_success_data(
        api_client.create_customer(create_customer_payload(name=name), FLEET_ADMIN))


def create_lane(**overrides):
    return get_success_data(
        api_client.create_lane(create_lane_payload(**overrides), LOAD_PLANNER))


def create_fuel_rate(**overrides):
    return get_success_data(api_client.create_state_fuel_rate(
        create_state_fuel_rate_payload(**overrides), FLEET_ADMIN))


def tender_load(customer_id, lane_id, **overrides):
    return get_success_data(api_client.create_load(
        create_load_payload(customer_id, lane_id, **overrides), LOAD_PLANNER))


def screen_load(load_id):
    return get_success_data(api_client.screen_load(load_id, LOAD_PLANNER))


def accept_load(load_id):
    return get_success_data(api_client.accept_load(load_id, LOAD_PLANNER))


def plan_trip(load_id, driver_id, tractor_id, **overrides):
    return get_success_data(api_client.create_trip(
        create_trip_payload(load_id, driver_id, tractor_id, **overrides), DISPATCHER))


def dispatch_trip(trip_id):
    return get_success_data(api_client.dispatch_trip(trip_id, DISPATCHER))


def post_duty_event(driver_id, **overrides):
    return get_success_data(api_client.create_duty_event(
        driver_id, create_duty_event_payload(**overrides),
        make_driver_headers(driver_id)))


def post_check_call(trip_id, driver_id, **overrides):
    return get_success_data(api_client.create_trip_check_call(
        trip_id, create_check_call_payload(**overrides),
        make_driver_headers(driver_id)))


def create_manual_accessorial(load_id, **overrides):
    return get_success_data(api_client.create_load_accessorial(
        load_id, create_accessorial_payload(**overrides), DISPATCHER))


def post_fuel_purchase(trip_id, driver_id, **overrides):
    return get_success_data(api_client.create_trip_fuel_purchase(
        trip_id, create_fuel_purchase_payload(driver_id, **overrides),
        make_driver_headers(driver_id)))


def record_safety_event(driver_id, **overrides):
    return get_success_data(api_client.create_safety_event(
        driver_id, create_safety_event_payload(**overrides), SAFETY_OFFICER))


def create_settlement_for(driver_id, user_id="payroll-1", **overrides):
    return get_success_data(api_client.create_settlement(
        create_settlement_payload(driver_id, **overrides),
        make_payroll_clerk_headers(user_id)))


def get_load(load_id):
    return get_success_data(api_client.get_load(load_id, DISPATCHER))


def get_trip(trip_id):
    return get_success_data(api_client.get_trip(trip_id, DISPATCHER))


def get_tractor(tractor_id):
    return get_success_data(api_client.get_tractor(tractor_id, DISPATCHER))


def get_driver(driver_id):
    return get_success_data(api_client.get_driver(driver_id, SAFETY_OFFICER))


def get_accessorial(accessorial_id):
    return get_success_data(api_client.get_accessorial(accessorial_id, LOAD_PLANNER))


def get_invoice(invoice_id):
    return get_success_data(api_client.get_invoice(invoice_id, LOAD_PLANNER))


def get_settlement(settlement_id):
    return get_success_data(api_client.get_settlement(settlement_id, PAYROLL_CLERK))


# ---------------------------------------------------------------------------
# Tier 2: reference-data preamble (customer + lane + national fuel rate)
# ---------------------------------------------------------------------------

def setup_refdata(pump_price_cents=450, with_national_rate=True,
                  clock=DEFAULT_CLOCK, lane_overrides=None):
    """Clock set; one ACTIVE customer; lane TX->GA 900mi floor 200 (unless
    overridden); the current US-NATIONAL fuel-rate row (unless suppressed)."""
    set_clock(clock)
    customer = create_customer()
    lane = create_lane(**(lane_overrides or {}))
    rate = create_fuel_rate(avg_pump_price_cents=pump_price_cents) \
        if with_national_rate else None
    return {"customer": customer, "lane": lane, "national_rate": rate}


def setup_accepted_load(rate_cents=250000, pump_price_cents=450,
                        lane_overrides=None, load_overrides=None,
                        clock=DEFAULT_CLOCK):
    """Reference data + load driven TENDERED -> SCREENED -> ACCEPTED."""
    ctx = setup_refdata(pump_price_cents=pump_price_cents, clock=clock,
                        lane_overrides=lane_overrides)
    # load_overrides wins over the positional rate_cents default; merging here
    # (rather than passing both) avoids a duplicate-keyword TypeError.
    load_kwargs = dict(load_overrides or {})
    load_kwargs.setdefault("rate_cents", rate_cents)
    load = tender_load(ctx["customer"]["id"], ctx["lane"]["id"], **load_kwargs)
    ctx["load"] = screen_load(load["id"])
    ctx["load"] = accept_load(load["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: trip lifecycle shortcuts
# ---------------------------------------------------------------------------

def setup_planned_trip(rate_cents=250000, pump_price_cents=450,
                       pay_model="MILEAGE", pay_rate_cents_per_mile=62,
                       pay_percentage_bp=None, last_home_at="2026-07-28T00:00:00Z",
                       lane_overrides=None, load_overrides=None,
                       trip_overrides=None, clock=DEFAULT_CLOCK,
                       cdl_number="CDL-F1", unit_number="T-F1"):
    """Full chain through trip creation: load ASSIGNED, tractor ASSIGNED,
    trip PLANNED with provisional pay computed."""
    ctx = setup_accepted_load(rate_cents=rate_cents,
                              pump_price_cents=pump_price_cents,
                              lane_overrides=lane_overrides,
                              load_overrides=load_overrides, clock=clock)
    driver_kwargs = {
        "cdl_number": cdl_number,
        "pay_model": pay_model,
        "last_home_at": last_home_at,
    }
    if pay_model == "MILEAGE":
        driver_kwargs["pay_rate_cents_per_mile"] = pay_rate_cents_per_mile
    if pay_percentage_bp is not None:
        driver_kwargs["pay_percentage_bp"] = pay_percentage_bp
    ctx["driver"] = create_driver(**driver_kwargs)
    ctx["tractor"] = create_tractor(unit_number=unit_number)
    ctx["trip"] = plan_trip(ctx["load"]["id"], ctx["driver"]["id"],
                            ctx["tractor"]["id"], **(trip_overrides or {}))
    return ctx


def setup_dispatched_trip(**kwargs):
    """Planned trip advanced through dispatch: trip DISPATCHED (start odometer
    snapshotted), load DISPATCHED."""
    ctx = setup_planned_trip(**kwargs)
    ctx["trip"] = dispatch_trip(ctx["trip"]["id"])
    return ctx


def complete_trip(trip_id, driver_id, *,
                  clock_to="2026-08-03T21:00:00Z",
                  arrive_pickup_at="2026-08-02T07:50:00Z",
                  depart_pickup_at="2026-08-02T10:00:00Z",
                  arrive_delivery_at="2026-08-03T17:00:00Z",
                  delivered_at="2026-08-03T21:00:00Z",
                  odometer_pickup=100120, odometer_delivery=101050,
                  delivery_state="GA"):
    """Drive a DISPATCHED trip to COMPLETED via the four milestone check calls
    (PRD §3.5). Default timings bill exactly 60 detention minutes on the
    delivery leg and zero on the pickup leg."""
    set_clock(clock_to)
    post_check_call(trip_id, driver_id, kind="ARRIVED_PICKUP",
                    occurred_at=arrive_pickup_at, state_code="TX",
                    odometer_miles=odometer_pickup)
    post_check_call(trip_id, driver_id, kind="DEPARTED_PICKUP",
                    occurred_at=depart_pickup_at, state_code="TX",
                    odometer_miles=odometer_pickup)
    post_check_call(trip_id, driver_id, kind="ARRIVED_DELIVERY",
                    occurred_at=arrive_delivery_at, state_code=delivery_state,
                    odometer_miles=odometer_delivery)
    return post_check_call(trip_id, driver_id, kind="DELIVERED",
                           occurred_at=delivered_at, state_code=delivery_state,
                           odometer_miles=odometer_delivery)


def setup_delivered_trip(**kwargs):
    """Full chain through DELIVERED with 60 billable delivery-detention minutes
    (auto DETENTION_DELIVERY charge, quantity 60, amount 6000, PENDING)."""
    ctx = setup_dispatched_trip(**kwargs)
    complete_trip(ctx["trip"]["id"], ctx["driver"]["id"])
    ctx["trip"] = get_trip(ctx["trip"]["id"])
    ctx["load"] = get_load(ctx["load"]["id"])
    return ctx


def setup_delivered_trip_no_detention(**kwargs):
    """Full chain through DELIVERED with every leg inside the free allowance,
    so no auto detention charge materializes (actual miles 1000)."""
    kwargs.setdefault("trip_overrides", {})
    ctx = setup_dispatched_trip(**kwargs)
    complete_trip(ctx["trip"]["id"], ctx["driver"]["id"],
                  clock_to="2026-08-03T19:00:00Z",
                  arrive_pickup_at="2026-08-02T08:00:00Z",
                  depart_pickup_at="2026-08-02T09:00:00Z",
                  arrive_delivery_at="2026-08-03T17:00:00Z",
                  delivered_at="2026-08-03T19:00:00Z",
                  odometer_delivery=101000)
    ctx["trip"] = get_trip(ctx["trip"]["id"])
    ctx["load"] = get_load(ctx["load"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: adjudication, invoicing, settlement
# ---------------------------------------------------------------------------

def adjudicate_to_approved(accessorial_id):
    """PENDING -> SUBMITTED (Dispatcher) -> APPROVED (LoadPlanner)."""
    get_success_data(api_client.submit_accessorial(accessorial_id, DISPATCHER))
    return get_success_data(api_client.approve_accessorial(accessorial_id,
                                                           LOAD_PLANNER))


def first_load_accessorial_id(load_id):
    rows = get_success_data(api_client.list_load_accessorials(load_id, DISPATCHER))
    assert isinstance(rows, list) and rows, "expected at least one accessorial"
    return rows[0]["id"]


def setup_issued_invoice(**kwargs):
    """Full chain: DELIVERED load with the auto detention charge adjudicated to
    APPROVED, DRAFT invoice created and ISSUED (accessorial -> BILLED)."""
    ctx = setup_delivered_trip(**kwargs)
    acc_id = first_load_accessorial_id(ctx["load"]["id"])
    ctx["accessorial"] = adjudicate_to_approved(acc_id)
    invoice = get_success_data(
        api_client.create_load_invoice(ctx["load"]["id"], LOAD_PLANNER))
    ctx["invoice"] = get_success_data(
        api_client.issue_invoice(invoice["id"], LOAD_PLANNER))
    ctx["load"] = get_load(ctx["load"]["id"])
    return ctx


def setup_settlement_after_invoice(user_id="payroll-1", **kwargs):
    """Issued-invoice chain plus a DRAFT settlement for the driver over
    [2026-08-01, 2026-08-08)."""
    ctx = setup_issued_invoice(**kwargs)
    ctx["settlement"] = create_settlement_for(ctx["driver"]["id"], user_id=user_id)
    return ctx
