"""Composite setup helpers for multi-step test prerequisites.

The harness restarts the API server before every test, so every helper builds
its preconditions from scratch against an empty database. Setup calls use
get_success_data() so a setup failure surfaces as a clear "Setup step failed"
error naming the failing call.
"""
from datetime import datetime, timedelta, timezone

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_customer_payload, create_vehicle_payload, create_driver_payload,
    create_quote_payload, create_breakdown_payload, create_trip_log_payload,
)
from .test_users import TEST_USERS, make_customer_headers
from .constants import DEFAULT_CLOCK_ISO

ADMIN = TEST_USERS["platform_admin_headers"]
AGENT = TEST_USERS["quote_agent_headers"]
DISPATCH = TEST_USERS["dispatch_manager_headers"]
FLEET = TEST_USERS["fleet_manager_headers"]
SAFETY = TEST_USERS["safety_officer_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# Tier 0: clock + single-entity creation
# ---------------------------------------------------------------------------

def set_clock(iso_str: str = DEFAULT_CLOCK_ISO):
    """Move the server's logical clock (PRD §2.6)."""
    res = api_client.set_current_utc({"to_iso8601": iso_str}, ADMIN)
    return get_success_data(res)


def make_customer(**overrides):
    res = api_client.create_customer(create_customer_payload(**overrides), AGENT)
    return get_success_data(res, 201)


def make_vehicle(**overrides):
    res = api_client.create_vehicle(create_vehicle_payload(**overrides), FLEET)
    return get_success_data(res, 201)


def make_driver(**overrides):
    res = api_client.create_driver(create_driver_payload(**overrides), FLEET)
    return get_success_data(res, 201)


def make_quote(customer_id: str, **overrides):
    res = api_client.create_quote(create_quote_payload(customer_id, **overrides), AGENT)
    return get_success_data(res, 201)


def price_quote(quote_id: str):
    """DRAFT -> QUOTED. Returns the priced quote."""
    res = api_client.price_quote(quote_id, AGENT)
    return get_success_data(res)


def accept_quote(quote_id: str, customer_id: str):
    """QUOTED -> ACCEPTED, creating the order. Returns the new CharterOrder."""
    quote = get_success_data(api_client.get_quote(quote_id, AGENT))
    res = api_client.accept_quote(
        quote_id, {"expected_quote_version": quote["version"]},
        make_customer_headers(customer_id))
    return get_success_data(res, 201)


def pay_full_deposit(order_id: str, customer_id: str):
    """Pay exactly the order's required deposit. Returns the CONFIRMED order."""
    order = get_success_data(api_client.get_order(order_id, DISPATCH))
    res = api_client.pay_deposit(
        order_id, {"amount_cents": order["deposit_cents"]},
        make_customer_headers(customer_id))
    return get_success_data(res)


def get_order(order_id: str):
    return get_success_data(api_client.get_order(order_id, DISPATCH))


def get_vehicle(vehicle_id: str):
    return get_success_data(api_client.get_vehicle(vehicle_id, FLEET))


def get_driver(driver_id: str):
    return get_success_data(api_client.get_driver(driver_id, FLEET))


def get_customer(customer_id: str):
    return get_success_data(api_client.get_customer(customer_id, AGENT))


def assign_order(order_id: str, vehicle_id: str, driver_id: str,
                 relief_driver_id: str = None):
    """CONFIRMED -> ASSIGNED with a fresh expected_order_version."""
    order = get_order(order_id)
    payload = {"vehicle_id": vehicle_id, "driver_id": driver_id,
               "expected_order_version": order["version"]}
    if relief_driver_id:
        payload["relief_driver_id"] = relief_driver_id
    res = api_client.assign_order(order_id, payload, DISPATCH)
    return get_success_data(res)


# ---------------------------------------------------------------------------
# Tier 2/3: lifecycle shortcuts (quote -> order states)
# ---------------------------------------------------------------------------

def setup_pending_deposit_order(customer_overrides=None, quote_overrides=None,
                                clock_iso=DEFAULT_CLOCK_ISO):
    """Customer + priced + accepted quote. Returns ctx dict with the
    PENDING_DEPOSIT order."""
    set_clock(clock_iso)
    customer = make_customer(**(customer_overrides or {}))
    quote = make_quote(customer["id"], **(quote_overrides or {}))
    quote = price_quote(quote["id"])
    order = accept_quote(quote["id"], customer["id"])
    return {"customer": customer, "quote": quote, "order": order}


def setup_confirmed_order(customer_overrides=None, quote_overrides=None,
                          clock_iso=DEFAULT_CLOCK_ISO):
    """Pending-deposit setup + full deposit payment. Order is CONFIRMED."""
    ctx = setup_pending_deposit_order(customer_overrides, quote_overrides, clock_iso)
    ctx["order"] = pay_full_deposit(ctx["order"]["id"], ctx["customer"]["id"])
    return ctx


def setup_assigned_order(customer_overrides=None, quote_overrides=None,
                         vehicle_overrides=None, driver_overrides=None,
                         clock_iso=DEFAULT_CLOCK_ISO):
    """Confirmed order + eligible vehicle/driver assigned. Order is ASSIGNED."""
    ctx = setup_confirmed_order(customer_overrides, quote_overrides, clock_iso)
    vehicle = make_vehicle(**(vehicle_overrides or {}))
    driver = make_driver(**(driver_overrides or {}))
    ctx["order"] = assign_order(ctx["order"]["id"], vehicle["id"], driver["id"])
    ctx["vehicle"] = vehicle
    ctx["driver"] = driver
    return ctx


def setup_in_progress_order(customer_overrides=None, quote_overrides=None,
                            vehicle_overrides=None, driver_overrides=None,
                            clock_iso=DEFAULT_CLOCK_ISO):
    """Assigned order + clock moved to trip_date - 30min + trip started.
    Order is IN_PROGRESS."""
    ctx = setup_assigned_order(customer_overrides, quote_overrides,
                               vehicle_overrides, driver_overrides, clock_iso)
    trip_dt = _parse(ctx["quote"]["trip_date"])
    set_clock(_iso(trip_dt - timedelta(minutes=30)))
    ctx["order"] = get_success_data(api_client.start_trip(ctx["order"]["id"], DISPATCH))
    return ctx


def setup_completed_order(actual_miles=100, actual_hours=4,
                          customer_overrides=None, quote_overrides=None,
                          vehicle_overrides=None, driver_overrides=None,
                          clock_iso="2026-07-01T00:00:00Z"):
    """Full lifecycle through COMPLETED. Default quote is a short same-day
    trip departing 2026-07-10T08:00Z. Returns ctx with final entities."""
    q_ov = {"trip_date": "2026-07-10T08:00:00Z",
            "return_date": "2026-07-10T14:00:00Z",
            "estimated_miles": 100, "estimated_hours": 4}
    q_ov.update(quote_overrides or {})
    ctx = setup_in_progress_order(customer_overrides, q_ov,
                                  vehicle_overrides, driver_overrides, clock_iso)
    ctx["order"] = get_success_data(api_client.complete_trip(
        ctx["order"]["id"],
        {"actual_miles": actual_miles, "actual_hours": actual_hours}, DISPATCH))
    ctx["vehicle"] = get_vehicle(ctx["vehicle"]["id"])
    ctx["driver"] = get_driver(ctx["driver"]["id"])
    ctx["customer"] = get_customer(ctx["customer"]["id"])
    return ctx


# ---------------------------------------------------------------------------
# Tier 3: breakdown setup
# ---------------------------------------------------------------------------

def setup_order_with_breakdown(customer_overrides=None, quote_overrides=None,
                               vehicle_overrides=None, driver_overrides=None,
                               clock_iso="2026-07-01T00:00:00Z"):
    """Order IN_PROGRESS + one REPORTED breakdown on the assigned vehicle."""
    q_ov = {"trip_date": "2026-07-10T08:00:00Z",
            "return_date": "2026-07-10T16:00:00Z",
            "estimated_miles": 300, "estimated_hours": 5}
    q_ov.update(quote_overrides or {})
    ctx = setup_in_progress_order(customer_overrides, q_ov,
                                  vehicle_overrides, driver_overrides, clock_iso)
    breakdown = get_success_data(api_client.report_breakdown(
        ctx["order"]["id"],
        create_breakdown_payload(ctx["vehicle"]["id"], ctx["driver"]["id"]),
        DISPATCH), 201)
    ctx["breakdown"] = breakdown
    return ctx


# ---------------------------------------------------------------------------
# Tier 4: HOS cycle-hours accumulation
# ---------------------------------------------------------------------------

def accumulate_driver_cycle_hours(driver_id: str, vehicle_id: str, customer_id: str,
                                  trips: int = 6, hours_each: float = 10,
                                  miles_each: int = 500,
                                  base_iso="2026-08-01T00:00:00Z"):
    """Drive `driver` through `trips` completed same-day trips of `hours_each`
    driving hours, resting >= 10h between trips, so the driver's
    current_cycle_hours accumulates (rest resets only the daily counters,
    not the cycle counter — PRD §3.2).

    Trip i departs at base + (6 + 20*i) hours: depart 06:00 day 0, then
    02:00/22:00/18:00/14:00/10:00 ... always 20h apart (10h trip + 10h rest).
    All trips land well inside the driver's 8-day cycle window.
    Returns the driver as last observed.
    """
    base = _parse(base_iso)
    driver = get_driver(driver_id)
    for i in range(trips):
        depart = base + timedelta(hours=6 + 20 * i)
        arrive = depart + timedelta(hours=hours_each)
        quote = make_quote(customer_id,
                           trip_date=_iso(depart), return_date=_iso(arrive),
                           estimated_miles=miles_each, estimated_hours=hours_each)
        quote = price_quote(quote["id"])
        order = accept_quote(quote["id"], customer_id)
        order = pay_full_deposit(order["id"], customer_id)
        assign_order(order["id"], vehicle_id, driver_id)
        set_clock(_iso(depart - timedelta(minutes=30)))
        get_success_data(api_client.start_trip(order["id"], DISPATCH))
        get_success_data(api_client.create_trip_log(
            order["id"],
            create_trip_log_payload(driver_id, log_type="DRIVING",
                                    start_time=_iso(depart), end_time=_iso(arrive),
                                    miles_driven=miles_each),
            DISPATCH), 201)
        get_success_data(api_client.complete_trip(
            order["id"], {"actual_miles": miles_each, "actual_hours": hours_each},
            DISPATCH))
        # Rest >= 10 consecutive hours, then force the lazy rest check.
        set_clock(_iso(arrive + timedelta(hours=10)))
        driver = get_success_data(api_client.check_driver_rest(driver_id, FLEET))
        assert driver["status"] == "AVAILABLE", (
            f"driver must be AVAILABLE after 10h rest, got {driver['status']}")
    return driver
