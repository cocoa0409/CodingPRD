"""Composite setup helpers — multi-step preambles tests can reuse.

Most interesting test claims require the system to be in a late state
that takes 5-15 API calls to reach. Each fixture composes the lower-
level steps so tests can focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

  When X-User-Role is Customer or Driver, X-User-ID is the id of the
  acting Customer or Driver and the server's ownership checks compare
  it to Parcel.customer_id, Route.driver_id, etc. After a fixture
  creates a Customer or Driver entity, any ownership-gated call made
  in the role of that entity MUST mint headers from
  make_customer_headers(customer["id"]) /
  make_driver_headers(driver["id"]) rather than fall back to the shared
  TEST_USERS["customer_headers"] / TEST_USERS["driver_headers"]
  constants. The shared constants are safe ONLY for non-ownership tests
  (auth probes, role-forbidden probes, 404 probes on missing resources).

CLOCK ANCHORING — PRD §2.11 / §3.5:

  Delivery-window enforcement, the rolling 30-day redelivery counter,
  and appointment feasibility all consult the logical clock. Each
  fixture pins absolute timestamps relative to a clock value the test
  author can advance to via advance_clock_to / advance_clock_by_*.

Setup calls use get_success_data (a lenient 2xx validator) so a failed
setup surfaces as 'Setup failed' rather than a downstream confusing
assertion failure.
"""
from __future__ import annotations

import math
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    AVG_SPEED_KMH,
    DEPART_HOUR_LOCAL,
    EARTH_RADIUS_KM,
    SERVICE_TIME_MIN,
    TEST_DEFAULTS,
)
from . import factories as _factories
from .factories import (
    add_days,
    add_hours,
    add_minutes,
    clock_advance_payload,
    create_address_payload,
    create_appointment_payload,
    create_attempt_payload,
    create_customer_payload,
    create_driver_payload,
    create_parcel_payload,
    create_route_payload,
    create_stop_payload,
    create_transit_center_payload,
    haversine_km,
    iso_utc,
    parse_iso,
    patch_customer_payload,
    random_three_letter_code,
    utcnow,
)
from .test_users import (
    TEST_USERS,
    make_customer_headers,
    make_driver_headers,
)


# ===========================================================================
# Logical clock helpers — PRD §2.11
# ===========================================================================
# Tracks the test-process's view of the logical clock so absolute
# targets can be derived without re-querying the server every call.
_CLOCK_LOCK = threading.Lock()
_CURRENT_CLOCK: Optional[datetime] = None


def _seed_clock() -> datetime:
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        if _CURRENT_CLOCK is None:
            _CURRENT_CLOCK = utcnow()
        return _CURRENT_CLOCK


def current_clock() -> datetime:
    """The test-process's view of the logical clock."""
    return _seed_clock()


# Install ourselves as the logical-clock provider so factory defaults
# (parcel time windows, route planned_date) follow PRD §2.11 forward-only
# clock instead of wall clock.
_factories.set_logical_now_provider(current_clock)


def current_clock_iso() -> str:
    return iso_utc(current_clock())


def reset_clock_tracker_to(dt: datetime) -> None:
    """Reset the in-process clock tracker to a known instant.
    Used by conftest's per-test reset bridge."""
    global _CURRENT_CLOCK
    with _CLOCK_LOCK:
        _CURRENT_CLOCK = dt


def advance_clock_to(target: datetime,
                     headers: Optional[Dict[str, str]] = None) -> datetime:
    """Advance the server's logical clock to `target` (UTC). Updates
    the test-process tracker. PRD §2.11: 'forward-only'."""
    global _CURRENT_CLOCK
    if headers is None:
        headers = TEST_USERS["dispatcher_headers"]
    target_iso = iso_utc(target)
    res = api_client.advance_clock(
        clock_advance_payload(target_iso), headers,
    )
    # Best-effort: tolerate non-2xx if the test deliberately moves
    # backwards; tests that expect rejection assert it themselves.
    if 200 <= res.status_code < 300:
        with _CLOCK_LOCK:
            _CURRENT_CLOCK = target
    return target


def advance_clock_by_hours(hours: float,
                           headers: Optional[Dict[str, str]] = None) -> datetime:
    return advance_clock_to(
        current_clock() + timedelta(hours=hours), headers,
    )


def advance_clock_by_days(days: float,
                          headers: Optional[Dict[str, str]] = None) -> datetime:
    return advance_clock_to(
        current_clock() + timedelta(days=days), headers,
    )


def advance_clock_by_minutes(
    minutes: float, headers: Optional[Dict[str, str]] = None,
) -> datetime:
    return advance_clock_to(
        current_clock() + timedelta(minutes=minutes), headers,
    )


# ===========================================================================
# Tier 1: Single-entity creation shortcuts
# ===========================================================================
def create_customer(driver_release_authorized: bool = False,
                    **overrides) -> Dict[str, Any]:
    """Create a Customer per PRD §3.1, with the optional
    driver_release_authorized flag set."""
    payload = create_customer_payload(
        driver_release_authorized=driver_release_authorized, **overrides,
    )
    res = api_client.create_customer(
        payload, TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(res)


def create_address(customer_id: str, **overrides) -> Dict[str, Any]:
    """Create an Address owned by a Customer (PRD §3.1).

    Identity threading: the Customer themselves may add an address,
    so we use make_customer_headers(customer_id) — a Dispatcher could
    also do it. Tests that probe ownership use the shared constant
    directly via api_client."""
    res = api_client.create_address(
        customer_id, create_address_payload(**overrides),
        make_customer_headers(customer_id),
    )
    return get_success_data(res)


def create_customer_with_default_address(
    driver_release_authorized: bool = False,
    address_overrides: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Customer + Address + set default_address_id. Returns (cust, addr)."""
    cust = create_customer(
        driver_release_authorized=driver_release_authorized,
    )
    addr = create_address(cust["id"], **(address_overrides or {}))
    patch_res = api_client.patch_customer(
        cust["id"],
        patch_customer_payload(default_address_id=addr["id"]),
        # PRD §2.1: a Customer may PATCH their own record. Use the
        # ownership-correct identity here so the call survives
        # ownership checks regardless of who else can PATCH.
        make_customer_headers(cust["id"]),
    )
    cust = get_success_data(patch_res)
    return cust, addr


def create_transit_center(
    hazmat_certified: bool = False,
    serviced_postal_prefixes: Optional[List[str]] = None,
    **overrides,
) -> Dict[str, Any]:
    """Create a TransitCenter per PRD §3.2."""
    if serviced_postal_prefixes is None:
        serviced_postal_prefixes = [
            TEST_DEFAULTS["transit_center_postal_prefix"],
        ]
    payload = create_transit_center_payload(
        code=overrides.pop("code", random_three_letter_code()),
        serviced_postal_prefixes=serviced_postal_prefixes,
        hazmat_certified=hazmat_certified,
        **overrides,
    )
    res = api_client.create_transit_center(
        payload, TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(res)


def create_driver(home_center_id: str,
                  hazmat_endorsement: bool = False,
                  **overrides) -> Dict[str, Any]:
    """Create a Driver per PRD §3.2."""
    payload = create_driver_payload(
        home_center_id=home_center_id,
        hazmat_endorsement=hazmat_endorsement,
        **overrides,
    )
    res = api_client.create_driver(
        payload, TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(res)


def check_in_driver(driver_id: str) -> Dict[str, Any]:
    """Driver -> ON_DUTY (PRD §3.2). The Driver may do this themselves;
    a Dispatcher may also do it on their behalf. We use the Driver's
    own identity so the call survives ownership checks if the
    implementation chooses to enforce them on this endpoint."""
    res = api_client.driver_check_in(
        driver_id, make_driver_headers(driver_id),
    )
    return get_success_data(res)


def _driver_check_out(driver_id: str) -> Dict[str, Any]:
    """Driver RETURNED -> OFF_DUTY (PRD §3.2). Used by multi-cycle
    composites that need to flip the driver back to OFF_DUTY before
    a second check-in."""
    res = api_client.driver_check_out(
        driver_id, make_driver_headers(driver_id),
    )
    return get_success_data(res)


# ===========================================================================
# Tier 2: Baseline scenario — one Customer / Address / Hub / Driver
# ===========================================================================
def setup_baseline(
    *,
    driver_release_authorized: bool = False,
    hazmat_certified: bool = False,
    hazmat_endorsement: bool = False,
    address_lat: float = TEST_DEFAULTS["address_lat"],
    address_lon: float = TEST_DEFAULTS["address_lon"],
    center_lat: float = TEST_DEFAULTS["transit_center_lat"],
    center_lon: float = TEST_DEFAULTS["transit_center_lon"],
    address_postal_code: str = TEST_DEFAULTS["address_postal_code"],
    serviced_postal_prefixes: Optional[List[str]] = None,
    residential: bool = True,
) -> Dict[str, Any]:
    """One Customer with default address + one hub + one driver.
    The hub services the address's postal prefix by default.

    Returns a dict with keys: customer, address, center, driver.
    """
    if serviced_postal_prefixes is None:
        serviced_postal_prefixes = [address_postal_code[:3]]
    cust, addr = create_customer_with_default_address(
        driver_release_authorized=driver_release_authorized,
        address_overrides={
            "latitude": address_lat,
            "longitude": address_lon,
            "postal_code": address_postal_code,
            "residential": residential,
        },
    )
    center = create_transit_center(
        hazmat_certified=hazmat_certified,
        serviced_postal_prefixes=serviced_postal_prefixes,
        latitude=center_lat,
        longitude=center_lon,
    )
    driver = create_driver(
        home_center_id=center["id"],
        hazmat_endorsement=hazmat_endorsement,
    )
    return {
        "customer": cust,
        "address": addr,
        "center": center,
        "driver": driver,
    }


# ===========================================================================
# Tier 3: Parcel-state progression — INDUCTED → ... → OUT_FOR_DELIVERY
# ===========================================================================
def create_parcel(customer_id: str, origin_center_id: str,
                  destination_address_id: Optional[str] = None,
                  **overrides) -> Dict[str, Any]:
    """POST /parcels (PRD §3.3). status starts at INDUCTED."""
    payload = create_parcel_payload(
        customer_id=customer_id,
        origin_center_id=origin_center_id,
        **overrides,
    )
    if destination_address_id is not None:
        payload["destination_address_id"] = destination_address_id
    res = api_client.create_parcel(
        payload, TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(res)


def induct_to_hub(parcel_id: str) -> Dict[str, Any]:
    """INDUCTED -> IN_TRANSIT_HUB (PRD §3.3)."""
    res = api_client.induct_parcel_to_hub(
        parcel_id, TEST_USERS["sorting_hub_operator_headers"],
    )
    return get_success_data(res)


def sort_parcel(parcel_id: str) -> Dict[str, Any]:
    """IN_TRANSIT_HUB -> SORTED (PRD §3.3)."""
    res = api_client.sort_parcel(
        parcel_id, TEST_USERS["sorting_hub_operator_headers"],
    )
    return get_success_data(res)


def walk_parcel_to_sorted(
    customer_id: str, origin_center_id: str,
    destination_address_id: Optional[str] = None, **overrides,
) -> Dict[str, Any]:
    """Create + induct + sort. Returns parcel in SORTED status."""
    parcel = create_parcel(
        customer_id, origin_center_id,
        destination_address_id=destination_address_id, **overrides,
    )
    induct_to_hub(parcel["id"])
    return sort_parcel(parcel["id"])


def create_route(center_id: str, driver_id: str,
                 planned_date: Optional[str] = None) -> Dict[str, Any]:
    res = api_client.create_route(
        create_route_payload(center_id, driver_id, planned_date),
        TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(res)


def add_stop(route_id: str, parcel_id: str) -> Dict[str, Any]:
    res = api_client.create_stop(
        route_id, create_stop_payload(parcel_id),
        TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(res)


def dispatch_route(route_id: str) -> Dict[str, Any]:
    res = api_client.dispatch_route(
        route_id, TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(res)


def close_route(route_id: str, driver_id: str) -> Dict[str, Any]:
    """Driver closes their own route (PRD §3.4). Identity-threaded
    via make_driver_headers because PRD §2.1 ties Driver ownership
    to Route.driver_id."""
    res = api_client.close_route(
        route_id, make_driver_headers(driver_id),
    )
    return get_success_data(res)


def walk_parcel_to_out_for_delivery(
    *,
    driver_release_authorized: bool = False,
    hazmat_certified: bool = False,
    hazmat_endorsement: bool = False,
    parcel_overrides: Optional[Dict[str, Any]] = None,
    planned_date: Optional[str] = None,
) -> Dict[str, Any]:
    """End-to-end progression to OUT_FOR_DELIVERY:
        baseline -> parcel -> induct -> sort -> route -> stop -> dispatch.
    Driver is checked in. Returns dict with keys:
        customer, address, center, driver, parcel, route, stop.
    """
    base = setup_baseline(
        driver_release_authorized=driver_release_authorized,
        hazmat_certified=hazmat_certified,
        hazmat_endorsement=hazmat_endorsement,
    )
    parcel = walk_parcel_to_sorted(
        customer_id=base["customer"]["id"],
        origin_center_id=base["center"]["id"],
        destination_address_id=base["address"]["id"],
        **(parcel_overrides or {}),
    )
    route = create_route(
        base["center"]["id"], base["driver"]["id"],
        planned_date=planned_date,
    )
    stop = add_stop(route["id"], parcel["id"])
    check_in_driver(base["driver"]["id"])
    dispatched = dispatch_route(route["id"])
    return {
        "customer": base["customer"],
        "address": base["address"],
        "center": base["center"],
        "driver": base["driver"],
        "parcel": parcel,
        "route": dispatched,
        "stop": stop,
    }


# ===========================================================================
# Tier 4: Delivery attempts and reattempt cycles
# ===========================================================================
def record_attempt(parcel_id: str, route_stop_id: str, driver_id: str,
                   outcome: str,
                   signature_blob_ref: Optional[str] = None,
                   release_location: Optional[str] = None,
                   ) -> Dict[str, Any]:
    """POST /parcels/{id}/attempts (PRD §3.5).

    Identity threading: PRD §2.1 ties Driver ownership to
    DeliveryAttempt.driver_id and Route.driver_id. Headers MUST be
    minted from the actual driver's id; using a shared constant would
    fail any ownership check that ties an attempt to the route's
    assigned driver.
    """
    payload = create_attempt_payload(
        route_stop_id, outcome,
        signature_blob_ref=signature_blob_ref,
        release_location=release_location,
    )
    res = api_client.create_attempt(
        parcel_id, payload, make_driver_headers(driver_id),
    )
    return get_success_data(res)


def move_clock_into_window(parcel: Dict[str, Any]) -> None:
    """Advance the logical clock so it lies between parcel
    time_window_start and time_window_end. Useful when the test
    cares about a delivery succeeding rather than testing the
    time-window guard itself."""
    start = parse_iso(parcel["time_window_start"])
    end = parse_iso(parcel["time_window_end"])
    midpoint = start + (end - start) / 2
    if current_clock() < midpoint:
        advance_clock_to(midpoint)


def deliver_signed(parcel: Dict[str, Any], stop: Dict[str, Any],
                   driver_id: str) -> Dict[str, Any]:
    """Successful DELIVERED_SIGNED inside the parcel's window."""
    move_clock_into_window(parcel)
    return record_attempt(
        parcel["id"], stop["id"], driver_id,
        outcome="DELIVERED_SIGNED",
        signature_blob_ref="sig-ref-" + parcel["id"][:8],
    )


def attempt_no_one_home(parcel: Dict[str, Any], stop: Dict[str, Any],
                        driver_id: str) -> Dict[str, Any]:
    """NO_ONE_HOME inside the parcel's window — clock is positioned
    in-window so the temporal guard does not gate this failure."""
    move_clock_into_window(parcel)
    return record_attempt(
        parcel["id"], stop["id"], driver_id, outcome="NO_ONE_HOME",
    )


def reattempt_parcel(parcel_id: str) -> Dict[str, Any]:
    """EXCEPTION -> SORTED (PRD §3.5)."""
    res = api_client.reattempt_parcel(
        parcel_id, TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(res)


def reset_driver_to_on_duty(driver_id: str, route_id: str) -> None:
    """Helper for multi-cycle reattempt scenarios.

    PRD §3.2 fixes the driver lifecycle as a four-state cycle:
        OFF_DUTY -> ON_DUTY -> ON_ROUTE -> RETURNED -> OFF_DUTY.

    After a failed delivery attempt the parcel sits in EXCEPTION, the
    driver is still ON_ROUTE, and the route is still IN_PROGRESS. To
    dispatch a NEW route for the redelivery cycle the driver must be
    ON_DUTY again — the only path back is close-the-route (driver to
    RETURNED) followed by check-out (driver to OFF_DUTY) followed by
    check-in (driver to ON_DUTY).
    """
    close_route(route_id, driver_id)
    _driver_check_out(driver_id)
    check_in_driver(driver_id)


def return_to_sender(parcel_id: str) -> Dict[str, Any]:
    """EXCEPTION -> RETURNED_TO_SENDER (PRD §3.5)."""
    res = api_client.return_to_sender(
        parcel_id, TEST_USERS["dispatcher_headers"],
    )
    return get_success_data(res)


# ===========================================================================
# Tier 5: Specialised composite fixtures for difficulty-design recipes
# ===========================================================================
def setup_parcel_in_exception(**baseline_kwargs) -> Dict[str, Any]:
    """Baseline -> parcel -> induct -> sort -> route -> stop -> dispatch
    -> NO_ONE_HOME attempt -> parcel now in EXCEPTION.
    Returns dict with: customer, address, center, driver, parcel,
    route, stop, attempt.
    """
    ctx = walk_parcel_to_out_for_delivery(**baseline_kwargs)
    attempt = attempt_no_one_home(
        ctx["parcel"], ctx["stop"], ctx["driver"]["id"],
    )
    parcel_after = get_success_data(api_client.get_parcel(
        ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
    ))
    return {**ctx, "parcel": parcel_after, "attempt": attempt}


def setup_quote_vs_final_divergence_scenario() -> Dict[str, Any]:
    """Difficulty rule_id=dual_variant_calc /
    parcel_quote_vs_final_fee_divergence.

    Walks a single parcel through INDUCTED -> ... -> first attempt
    NO_ONE_HOME -> reattempt -> second attempt DELIVERED_SIGNED so
    final_fee = quoted_fee + REATTEMPT_FEE.
    Returns dict with keys: customer, address, center, driver, parcel,
    quoted_fee, route1, route2.
    """
    ctx = walk_parcel_to_out_for_delivery(
        driver_release_authorized=True,
    )
    quoted_fee = ctx["parcel"]["quoted_fee"]
    # First attempt fails.
    attempt_no_one_home(ctx["parcel"], ctx["stop"], ctx["driver"]["id"])
    # Close route1 so the driver can come back to OFF_DUTY (PRD §3.2:
    # the four-state cycle OFF_DUTY -> ON_DUTY -> ON_ROUTE -> RETURNED
    # -> OFF_DUTY).
    close_route(ctx["route"]["id"], ctx["driver"]["id"])
    # Check-out drops driver from RETURNED back to OFF_DUTY so we can
    # check-in for the next route.
    _driver_check_out(ctx["driver"]["id"])
    # Reattempt -> SORTED.
    reattempt_parcel(ctx["parcel"]["id"])
    # PRD §3.7: pin the new route's planned_date to the parcel's
    # window date so stop assignment stays in-window (reattempt does
    # NOT re-set the parcel window per PRD §3.5).
    parcel_window_date = ctx["parcel"]["time_window_start"][:10]
    # New route -> new stop -> dispatch -> deliver_signed.
    route2 = create_route(
        ctx["center"]["id"], ctx["driver"]["id"],
        planned_date=parcel_window_date,
    )
    stop2 = add_stop(route2["id"], ctx["parcel"]["id"])
    # Driver is OFF_DUTY post check-out; check-in to ON_DUTY for dispatch.
    check_in_driver(ctx["driver"]["id"])
    dispatch_route(route2["id"])
    # Re-fetch parcel and deliver.
    parcel_after = get_success_data(api_client.get_parcel(
        ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
    ))
    deliver_signed(parcel_after, stop2, ctx["driver"]["id"])
    final_parcel = get_success_data(api_client.get_parcel(
        ctx["parcel"]["id"], TEST_USERS["dispatcher_headers"],
    ))
    return {
        "customer": ctx["customer"],
        "address": ctx["address"],
        "center": ctx["center"],
        "driver": ctx["driver"],
        "parcel": final_parcel,
        "quoted_fee": quoted_fee,
        "route1": ctx["route"],
        "route2": route2,
    }


def setup_three_sorted_parcels_one_route(
    parcel_count: int = 3,
) -> Dict[str, Any]:
    """Compensating-invariant scenario for rule_id=compensating_invariant
    /route_cancel_restores_parcel_belt_state.

    Creates N parcels in SORTED at one hub, then a PLANNED Route +
    all N stops attached (so all parcels move to ON_VEHICLE).
    Returns dict: customer, address, center, driver, parcels, route, stops.
    Time windows are generous so all stops are time-feasible.
    """
    base = setup_baseline()
    parcels: List[Dict[str, Any]] = []
    for _ in range(parcel_count):
        p = walk_parcel_to_sorted(
            customer_id=base["customer"]["id"],
            origin_center_id=base["center"]["id"],
            destination_address_id=base["address"]["id"],
        )
        parcels.append(p)
    route = create_route(base["center"]["id"], base["driver"]["id"])
    stops: List[Dict[str, Any]] = []
    for p in parcels:
        stops.append(add_stop(route["id"], p["id"]))
    return {
        **base,
        "parcels": parcels,
        "route": route,
        "stops": stops,
    }


def setup_route_with_n_stops(parcel_count: int = 2,
                             dispatch: bool = False) -> Dict[str, Any]:
    """Generic helper: create a baseline + a route + N parcel stops
    in SORTED→ON_VEHICLE, optionally dispatched."""
    ctx = setup_three_sorted_parcels_one_route(
        parcel_count=parcel_count,
    )
    if dispatch:
        check_in_driver(ctx["driver"]["id"])
        ctx["route"] = dispatch_route(ctx["route"]["id"])
    return ctx


def setup_appointment_on_exception_parcel(
    appt_offset_hours: float = 5.0,
    appt_window_hours: float = 3.0,
) -> Dict[str, Any]:
    """Difficulty rule_id=transitive_cascade / reattempt_cascade_depth_2:
    parcel in EXCEPTION + a PENDING Appointment for it. Returns dict
    with keys: customer, address, center, driver, parcel, route, stop,
    attempt, appointment.
    """
    ctx = setup_parcel_in_exception()
    start = current_clock() + timedelta(hours=appt_offset_hours)
    end = start + timedelta(hours=appt_window_hours)
    appt = get_success_data(api_client.create_appointment(
        create_appointment_payload(
            parcel_id=ctx["parcel"]["id"],
            requested_window_start=iso_utc(start),
            requested_window_end=iso_utc(end),
        ),
        make_customer_headers(ctx["customer"]["id"]),
    ))
    return {**ctx, "appointment": appt}


__all__ = [
    # clock
    "current_clock",
    "current_clock_iso",
    "reset_clock_tracker_to",
    "advance_clock_to",
    "advance_clock_by_hours",
    "advance_clock_by_days",
    "advance_clock_by_minutes",
    # Tier 1
    "create_customer",
    "create_address",
    "create_customer_with_default_address",
    "create_transit_center",
    "create_driver",
    "check_in_driver",
    # Tier 2
    "setup_baseline",
    # Tier 3
    "create_parcel",
    "induct_to_hub",
    "sort_parcel",
    "walk_parcel_to_sorted",
    "create_route",
    "add_stop",
    "dispatch_route",
    "close_route",
    "walk_parcel_to_out_for_delivery",
    # Tier 4
    "record_attempt",
    "move_clock_into_window",
    "deliver_signed",
    "attempt_no_one_home",
    "reattempt_parcel",
    "reset_driver_to_on_duty",
    "return_to_sender",
    # Tier 5
    "setup_parcel_in_exception",
    "setup_quote_vs_final_divergence_scenario",
    "setup_three_sorted_parcels_one_route",
    "setup_route_with_n_stops",
    "setup_appointment_on_exception_parcel",
]
