"""Composite setup helpers.

Most interesting claims require the system to be walked through several API calls
to reach a specific state. These helpers encapsulate those multi-step preambles
so test functions can focus on the trigger + assertion. All setup uses
get_success_data() (lenient) so a broken precondition surfaces as a clear
"Setup step failed" error rather than a confusing later assertion failure.

The harness restarts the server (empty DB) before every test, so each helper
builds its world from scratch using only PRD-declared endpoints.

Identity threading: after creating an entity_backed Rider/Technician, any
ownership-gated call uses make_rider_headers(rider["id"]) /
make_technician_headers(tech["id"]) — never the shared TEST_USERS fallback.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client as _api
from .test_users import (
    TEST_USERS,
    make_rider_headers,
    make_technician_headers,
    make_regulator_headers,
)
from . import factories as f


_ADMIN = TEST_USERS["admin_headers"]
_ANON = TEST_USERS["anonymous_headers"]


# ---------------------------------------------------------------------------
# Tier 0: clock control + primitives
# ---------------------------------------------------------------------------
def set_clock(iso: str):
    """Pin the server's logical UTC clock (PRD §3.9)."""
    get_success_data(_api.set_clock(f.set_clock_payload(iso), _ADMIN))


def set_battery(vehicle_id: str, battery_pct: int):
    """Pin a vehicle's battery_pct (PRD §3.9; no version/status change)."""
    get_success_data(_api.set_battery(vehicle_id, f.set_battery_payload(battery_pct), _ADMIN))


def create_plan(**overrides) -> dict:
    return get_success_data(_api.create_plan(f.create_plan_payload(**overrides), _ADMIN))


def create_standard_plan(**overrides) -> dict:
    """STANDARD plan: unlock 100, per_min 30, cap 0, slow_disc 0 unless overridden."""
    payload = dict(code="STANDARD", unlock_fee_cents=100, per_minute_cents=30,
                   daily_cap_cents=0, slow_zone_discount_pct=0)
    payload.update(overrides)
    return create_plan(**payload)


def create_low_income_plan(**overrides) -> dict:
    """LOW_INCOME plan: unlock 50, per_min 15, cap 500, slow_disc 0.50 unless overridden."""
    payload = dict(code="LOW_INCOME", unlock_fee_cents=50, per_minute_cents=15,
                   daily_cap_cents=500, slow_zone_discount_pct=0.50)
    payload.update(overrides)
    return create_plan(**payload)


def create_zone(**overrides) -> dict:
    return get_success_data(_api.create_zone(f.create_zone_payload(**overrides), _ADMIN))


def create_vehicle(zone_id: str, **overrides) -> dict:
    payload = f.create_vehicle_payload(current_zone_id=zone_id, **overrides)
    return get_success_data(_api.create_vehicle(payload, _ADMIN))


def create_technician(zone_id: str, **overrides) -> dict:
    payload = f.create_technician_payload(depot_zone_id=zone_id, **overrides)
    return get_success_data(_api.create_technician(payload, _ADMIN))


def create_rider(plan_id: str, **overrides) -> dict:
    """Self-register a rider (Anonymous)."""
    payload = f.create_rider_payload(plan_id=plan_id, **overrides)
    return get_success_data(_api.create_rider(payload, _ANON))


def topup(rider: dict, amount_cents: int = 5000) -> dict:
    """Top up the rider's wallet; returns the updated rider after re-fetch."""
    headers = make_rider_headers(rider["id"])
    get_success_data(_api.topup_rider(rider["id"], f.topup_payload(amount_cents=amount_cents), headers))
    return get_success_data(_api.get_rider(rider["id"], headers))


def create_funded_rider(plan_id: str, amount_cents: int = 5000, **overrides) -> dict:
    """Register a rider on plan_id and fund the wallet. Returns the rider after topup."""
    rider = create_rider(plan_id, **overrides)
    return topup(rider, amount_cents)


# ---------------------------------------------------------------------------
# Tier 1: environment setup (plan + zone + vehicle)
# ---------------------------------------------------------------------------
def setup_world(plan_overrides=None, zone_type="RIDE_OK", zone_overrides=None,
                vehicle_overrides=None):
    """STANDARD plan + one zone + one vehicle parked in it.

    Returns (plan, zone, vehicle). The default world is a STANDARD plan, a
    RIDE_OK zone, and a SCOOTER at battery 100.
    """
    plan = create_standard_plan(**(plan_overrides or {}))
    zopts = dict(zone_type=zone_type)
    zopts.update(zone_overrides or {})
    zone = create_zone(**zopts)
    vehicle = create_vehicle(zone["id"], **(vehicle_overrides or {}))
    return plan, zone, vehicle


# ---------------------------------------------------------------------------
# Tier 2: low-income rider via approved application
# ---------------------------------------------------------------------------
def make_low_income_rider(std_plan_id: str, li_plan_id: str, amount_cents: int = 10000,
                          household_size: int = 2, annual_income_cents: int = 4000000) -> dict:
    """Register a rider on STANDARD, fund, submit + approve a low-income application,
    then switch the rider to the LOW_INCOME plan (OCC with the live version).

    Returns the rider after the plan switch.
    """
    rider = create_rider(std_plan_id)
    headers = make_rider_headers(rider["id"])
    funded = topup(rider, amount_cents)
    app = get_success_data(_api.create_low_income_application(
        f.create_low_income_application_payload(
            rider_id=rider["id"], household_size=household_size,
            annual_income_cents=annual_income_cents),
        headers))
    get_success_data(_api.approve_low_income_application(app["id"], _ADMIN))
    get_success_data(_api.change_plan(
        rider["id"],
        f.change_plan_payload(plan_id=li_plan_id, expected_rider_version=funded["version"]),
        headers))
    return get_success_data(_api.get_rider(rider["id"], headers))


# ---------------------------------------------------------------------------
# Tier 3: trip lifecycle shortcuts
# ---------------------------------------------------------------------------
def start_trip(rider: dict, vehicle: dict, start_iso: str = None) -> dict:
    """Optionally pin the clock, then unlock the vehicle. Returns the ACTIVE trip."""
    if start_iso is not None:
        set_clock(start_iso)
    headers = make_rider_headers(rider["id"])
    return get_success_data(_api.create_trip(
        f.create_trip_payload(rider_id=rider["id"], vehicle_id=vehicle["id"]), headers))


def end_trip(rider: dict, trip: dict, end_zone_id: str, end_iso: str = None) -> dict:
    """Optionally pin the clock, then end the trip in end_zone_id. Returns the trip."""
    if end_iso is not None:
        set_clock(end_iso)
    headers = make_rider_headers(rider["id"])
    return get_success_data(_api.end_trip(
        trip["id"], f.end_trip_payload(end_zone_id=end_zone_id), headers))


def setup_completed_trip(start_iso, end_iso, end_zone_id=None, plan_overrides=None,
                         vehicle_overrides=None, amount_cents=5000):
    """STANDARD plan + RIDE_OK zone + vehicle + funded rider; start a trip at
    start_iso and end it at end_iso in end_zone_id (defaults to the start zone).

    Returns (plan, zone, vehicle, rider, trip) where trip is the COMPLETED trip.
    """
    plan, zone, vehicle = setup_world(plan_overrides=plan_overrides,
                                      vehicle_overrides=vehicle_overrides)
    rider = create_funded_rider(plan["id"], amount_cents=amount_cents)
    trip = start_trip(rider, vehicle, start_iso)
    trip = end_trip(rider, trip, end_zone_id or zone["id"], end_iso)
    return plan, zone, vehicle, rider, trip


def setup_active_trip(start_iso, plan_overrides=None, vehicle_overrides=None,
                      amount_cents=5000):
    """STANDARD plan + RIDE_OK zone + vehicle + funded rider; start (but do not end)
    a trip at start_iso. Returns (plan, zone, vehicle, rider, trip)."""
    plan, zone, vehicle = setup_world(plan_overrides=plan_overrides,
                                      vehicle_overrides=vehicle_overrides)
    rider = create_funded_rider(plan["id"], amount_cents=amount_cents)
    trip = start_trip(rider, vehicle, start_iso)
    return plan, zone, vehicle, rider, trip


# ---------------------------------------------------------------------------
# Tier 3b: no-park trip raising a fine
# ---------------------------------------------------------------------------
def setup_trip_ended_in_no_park(start_iso, end_iso, plan_overrides=None,
                                vehicle_overrides=None, amount_cents=5000):
    """STANDARD plan + RIDE_OK zone + NO_PARK zone + vehicle + funded rider; ride
    and end the trip in the NO_PARK zone, raising one PENDING fine.

    Returns (plan, ok_zone, np_zone, vehicle, rider, trip, fine).
    """
    plan = create_standard_plan(**(plan_overrides or {}))
    ok_zone = create_zone(zone_type="RIDE_OK", priority=5)
    np_zone = create_zone(zone_type="NO_PARK", priority=3)
    vehicle = create_vehicle(ok_zone["id"], **(vehicle_overrides or {}))
    rider = create_funded_rider(plan["id"], amount_cents=amount_cents)
    trip = start_trip(rider, vehicle, start_iso)
    trip = end_trip(rider, trip, np_zone["id"], end_iso)
    fine = _fetch_only_fine(rider)
    return plan, ok_zone, np_zone, vehicle, rider, trip, fine


def _fetch_only_fine(rider: dict) -> dict:
    headers = make_rider_headers(rider["id"])
    data, _ = _paginate(_api.list_fines(headers, params={"rider_id": rider["id"]}))
    assert data, f"expected a fine for rider {rider['id']}, got none"
    return data[0]


def _paginate(response):
    body = get_success_data_with_meta(response)
    return body["data"], body["meta"]


def get_success_data_with_meta(response):
    """Lenient success that also returns meta (for list endpoints in setup)."""
    if not (200 <= response.status_code < 300):
        raise AssertionError(
            f"Setup list step failed with HTTP {response.status_code}: {response.text}")
    return response.json()


# ---------------------------------------------------------------------------
# Tier 4: paused/resumed (multi-segment) trips for billable-minutes precision
# ---------------------------------------------------------------------------
def setup_paused_resumed_trip(timeline, plan_overrides=None, vehicle_overrides=None,
                              zone_type="RIDE_OK", zone_overrides=None):
    """Build a trip that is paused/resumed according to `timeline`, then ended.

    `timeline` is a list of (action, iso) tuples where action is one of
    'start', 'pause', 'resume', 'end'. The end zone is the trip's start zone.
    Returns (plan, zone, vehicle, rider, trip) with trip COMPLETED.
    """
    plan = create_standard_plan(**(plan_overrides or {}))
    zopts = dict(zone_type=zone_type, priority=5)
    zopts.update(zone_overrides or {})
    zone = create_zone(**zopts)
    vehicle = create_vehicle(zone["id"], **(vehicle_overrides or {}))
    rider = create_funded_rider(plan["id"])
    headers = make_rider_headers(rider["id"])
    trip = None
    for action, iso in timeline:
        set_clock(iso)
        if action == "start":
            trip = get_success_data(_api.create_trip(
                f.create_trip_payload(rider_id=rider["id"], vehicle_id=vehicle["id"]), headers))
        elif action == "pause":
            trip = get_success_data(_api.pause_trip(trip["id"], headers))
        elif action == "resume":
            trip = get_success_data(_api.resume_trip(trip["id"], headers))
        elif action == "end":
            trip = get_success_data(_api.end_trip(
                trip["id"], f.end_trip_payload(end_zone_id=zone["id"]), headers))
        else:
            raise ValueError(f"unknown timeline action {action!r}")
    return plan, zone, vehicle, rider, trip


# ---------------------------------------------------------------------------
# Tier 5: rebalancing tasks
# ---------------------------------------------------------------------------
def create_move_task(vehicle: dict, target_zone_id: str, window_start, window_end):
    """Create an OPEN MOVE task against vehicle at its current version.

    Returns (task, vehicle_after) where vehicle_after reflects the bumped version.
    """
    task = get_success_data(_api.create_rebalancing_task(
        f.create_rebalancing_task_payload(
            vehicle_id=vehicle["id"], task_type="MOVE", target_zone_id=target_zone_id,
            window_start=window_start, window_end=window_end,
            expected_vehicle_version=vehicle["version"]),
        _ADMIN))
    vehicle_after = get_success_data(_api.get_vehicle(vehicle["id"], _ADMIN))
    return task, vehicle_after


def assign_task(task: dict, technician: dict) -> dict:
    return get_success_data(_api.assign_rebalancing_task(
        task["id"], f.assign_task_payload(technician_id=technician["id"]), _ADMIN))


def setup_low_battery_swap_task(start_iso, end_iso, amount_cents=5000):
    """Start a trip on a vehicle, force battery to 10, end the trip in a legal zone
    so the vehicle lands LOW_BATTERY and auto-spawns an OPEN SWAP task.

    Returns (plan, zone, vehicle, rider, trip, swap_task).
    """
    plan, zone, vehicle = setup_world(vehicle_overrides={"battery_pct": 20})
    rider = create_funded_rider(plan["id"], amount_cents=amount_cents)
    trip = start_trip(rider, vehicle, start_iso)
    set_battery(vehicle["id"], 10)
    trip = end_trip(rider, trip, zone["id"], end_iso)
    data, _ = _paginate(_api.list_rebalancing_tasks(_ADMIN, params={"vehicle_id": vehicle["id"]}))
    assert data, f"expected an auto-created swap task for vehicle {vehicle['id']}"
    return plan, zone, vehicle, rider, trip, data[0]
