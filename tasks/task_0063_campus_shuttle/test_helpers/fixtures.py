"""Composite setup helpers for the Campus Shuttle Dispatch test suite.

Most interesting test claims need the system to be in a state reached
through 5-15 API calls (stop create -> activate -> route create -> publish
-> vehicle create -> driver create -> run-sheet create -> board -> ...).
This file encapsulates those preambles so tests focus on assertions.

Identity threading (PRD §2.1):
- Driver is ENTITY-BACKED:Driver. Every Driver-role call whose success
  depends on the resource referencing this driver MUST use
  make_driver_headers(driver["id"]).
- Employee is OPAQUE but its X-User-ID "is carried through to the
  employee_id field on a new reservation and used to scope cancellation
  and listing." Helpers therefore set X-User-ID == employee_id so cancel
  / list semantics resolve under either interpretation.
- Dispatcher and Auditor are OPAQUE.

Setup helpers use get_success_data (lenient) so a broken precondition
surfaces as a clear setup error rather than a confusing assertion deep
inside a test body.
"""
from __future__ import annotations
import math
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import (
    AVG_SPEED_KMH,
    DWELL_MIN_PER_INTERMEDIATE,
    PEAK_FACTOR,
    PEAK_FARE_MULTIPLIER,
    VEHICLE_OCCUPATION_BUFFER_MIN,
    expected_route_distance_km,
    expected_base_duration_minutes,
    expected_peak_adjusted_duration_minutes,
)
from .factories import (
    check_in_payload,
    clock_advance_payload,
    create_bill_payload,
    create_driver_payload,
    create_reservation_payload,
    create_route_payload,
    create_run_sheet_payload,
    create_stop_payload,
    create_vehicle_payload,
    date_z,
    dispatch_substitute_payload,
    iso_z,
    parse_iso,
    report_delay_payload,
    start_maintenance_payload,
    unique_department_code,
    unique_employee_code,
    unique_plate_number,
    unique_route_code,
    unique_stop_code,
    unique_suffix,
    update_ridership_payload,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
    make_employee_headers,
)


# ===========================================================================
# Shared opaque headers
# ===========================================================================
DISP = TEST_USERS["dispatcher_headers"]
DISP_ALT = TEST_USERS["dispatcher_headers_alt"]
AUD = TEST_USERS["auditor_headers"]


# ===========================================================================
# Clock helpers (PRD §2.12)
# ===========================================================================
def advance_clock_to(to_iso: str,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """PRD §2.12: 'A test-driving capability advances the system clock to a
    supplied to_timestamp ISO 8601 UTC instant.'"""
    return get_success_data(api_client.advance_clock(
        clock_advance_payload(to_iso), headers or DISP,
    ))


def get_server_now_iso() -> str:
    """Read the server's current api_request_timestamp via a cheap GET."""
    resp = api_client.list_audit_logs(DISP, params={"limit": 1, "offset": 0})
    return resp.json().get("meta", {}).get("api_request_timestamp", "")


def get_server_now_dt() -> datetime:
    """Convenience wrapper returning a tz-aware UTC datetime."""
    ts = get_server_now_iso()
    if ts:
        return parse_iso(ts)
    return datetime.now(timezone.utc)


# ===========================================================================
# Stops (PRD §3.1)
# ===========================================================================
def create_draft_stop(**overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_stop(
        create_stop_payload(**overrides), DISP,
    ))


def create_active_stop(**overrides: Any) -> Dict[str, Any]:
    """Create a stop and immediately activate it (PRD §3.1)."""
    stop = create_draft_stop(**overrides)
    return get_success_data(api_client.activate_stop(stop["id"], DISP))


def create_active_stop_at(latitude: float, longitude: float,
                          **overrides: Any) -> Dict[str, Any]:
    """Active stop at a precise lat/lng — used for distance/duration tests."""
    return create_active_stop(latitude=latitude, longitude=longitude,
                              **overrides)


# ===========================================================================
# Drivers (PRD §3.3)
# ===========================================================================
def create_active_driver(license_expiry_date: Optional[str] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """Drivers begin ACTIVE per PRD §3.3 ('A driver's status begins at ACTIVE')."""
    return get_success_data(api_client.create_driver(
        create_driver_payload(license_expiry_date=license_expiry_date,
                              **overrides),
        DISP,
    ))


# ===========================================================================
# Vehicles (PRD §3.3)
# ===========================================================================
def create_active_vehicle(seat_capacity: int = 20,
                          plate_number: Optional[str] = None,
                          vehicle_type: str = "STANDARD",
                          **overrides: Any) -> Dict[str, Any]:
    """Vehicles begin ACTIVE per PRD §3.3 ('Vehicles begin in ACTIVE status')."""
    payload_overrides = dict(overrides)
    payload_overrides.setdefault("seat_capacity", seat_capacity)
    payload_overrides.setdefault("vehicle_type", vehicle_type)
    if plate_number is not None:
        payload_overrides["plate_number"] = plate_number
    return get_success_data(api_client.create_vehicle(
        create_vehicle_payload(**payload_overrides), DISP,
    ))


def start_vehicle_maintenance(vehicle_id: str, window_start_iso: str,
                              window_end_iso: str) -> Dict[str, Any]:
    return get_success_data(api_client.start_vehicle_maintenance(
        vehicle_id,
        start_maintenance_payload(window_start_iso, window_end_iso),
        DISP,
    ))


# ===========================================================================
# Routes (PRD §3.2)
# ===========================================================================
def create_draft_route(start_stop_id: str, end_stop_id: str,
                       intermediate_stop_ids: Optional[List[str]] = None,
                       **overrides: Any) -> Dict[str, Any]:
    return get_success_data(api_client.create_route(
        create_route_payload(start_stop_id, end_stop_id,
                             intermediate_stop_ids, **overrides),
        DISP,
    ))


def publish_route(route_id: str) -> Dict[str, Any]:
    """PRD §3.2 publish: returns the now-ACTIVE Route with computed fields."""
    return get_success_data(api_client.publish_route(route_id, DISP))


def create_and_publish_route(start_stop_id: str, end_stop_id: str,
                             intermediate_stop_ids: Optional[List[str]] = None,
                             **overrides: Any) -> Dict[str, Any]:
    """Create DRAFT route + publish in one step."""
    route = create_draft_route(start_stop_id, end_stop_id,
                               intermediate_stop_ids, **overrides)
    return publish_route(route["id"])


def retire_route(route_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.retire_route(route_id, DISP))


# ===========================================================================
# Tier 2: Active-shuttle topology
# ===========================================================================
def setup_two_active_stops(lat1: float = 0.0, lng1: float = 0.0,
                           lat2: float = 0.0, lng2: float = 0.05,
                           ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create two ACTIVE stops with known coordinates."""
    s1 = create_active_stop_at(lat1, lng1)
    s2 = create_active_stop_at(lat2, lng2)
    return s1, s2


def setup_four_active_stops_in_line(spacing_lng: float = 0.01
                                    ) -> List[Dict[str, Any]]:
    """Four ACTIVE stops on the equator separated by `spacing_lng` degrees of longitude.

    Each adjacent pair is roughly 1.112 km apart at the equator.
    Used for distance / duration tests that need a known stop sequence.
    """
    return [create_active_stop_at(0.0, i * spacing_lng) for i in range(4)]


def setup_active_route_basic(*,
                             peak_windows: Optional[List[List[str]]] = None,
                             peak_frequency_minutes: int = 10,
                             offpeak_frequency_minutes: int = 30,
                             intermediate_count: int = 0,
                             stop_spacing_lng: float = 0.05,
                             ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """ACTIVE Route + ACTIVE stops.

    Returns (route, ordered_stops). Stops are ACTIVE at the time of publish.
    """
    if peak_windows is None:
        peak_windows = [["09:00", "11:00"]]
    total_stops = 2 + intermediate_count
    stops = [create_active_stop_at(0.0, i * stop_spacing_lng)
             for i in range(total_stops)]
    route = create_and_publish_route(
        start_stop_id=stops[0]["id"],
        end_stop_id=stops[-1]["id"],
        intermediate_stop_ids=[s["id"] for s in stops[1:-1]],
        peak_windows=peak_windows,
        peak_frequency_minutes=peak_frequency_minutes,
        offpeak_frequency_minutes=offpeak_frequency_minutes,
    )
    return route, stops


# ===========================================================================
# Tier 3: Run-sheets (PRD §3.4)
# ===========================================================================
def create_run_sheet(route_id: str, scheduled_departure_iso: str,
                     driver_id: str, *,
                     vehicle_id: Optional[str] = None,
                     scheduled_date_iso: Optional[str] = None,
                     headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    return get_success_data(api_client.create_run_sheet(
        create_run_sheet_payload(
            route_id=route_id,
            scheduled_departure=scheduled_departure_iso,
            assigned_driver_id=driver_id,
            scheduled_date=scheduled_date_iso,
            assigned_vehicle_id=vehicle_id,
        ),
        headers or DISP,
    ))


def setup_planned_run_sheet(*,
                            scheduled_departure_iso: Optional[str] = None,
                            peak_windows: Optional[List[List[str]]] = None,
                            seat_capacity: int = 20,
                            intermediate_count: int = 0,
                            ) -> Dict[str, Any]:
    """End-to-end fixture: stops -> route -> vehicle -> driver -> PLANNED run-sheet.

    PRD §3.3 constrains seat_capacity to be in [8, 80]. Callers that ask for a
    smaller "logical capacity" (e.g. seat_capacity=1 for waitlist scenarios)
    get a vehicle with the PRD-minimum capacity of 8 and the run-sheet is
    prefilled with (8 - requested) dummy CONFIRMED reservations, so that the
    run's `capacity_remaining` at fixture return equals the requested value.

    Returns a dict with: stops, route, vehicle, driver, run_sheet.
    """
    PRD_MIN_SEAT_CAPACITY = 8
    logical_capacity = seat_capacity
    actual_capacity = max(seat_capacity, PRD_MIN_SEAT_CAPACITY)
    route, stops = setup_active_route_basic(
        peak_windows=peak_windows,
        intermediate_count=intermediate_count,
    )
    vehicle = create_active_vehicle(seat_capacity=actual_capacity)
    # Anchor schedule on the current server clock so license expiry / windows resolve.
    now = get_server_now_dt()
    if scheduled_departure_iso is None:
        scheduled_departure_iso = iso_z(
            (now + timedelta(hours=2)).replace(microsecond=0),
        )
    driver_license = iso_z(parse_iso(scheduled_departure_iso) + timedelta(days=180))
    driver = create_active_driver(license_expiry_date=driver_license)
    run_sheet = create_run_sheet(
        route_id=route["id"],
        scheduled_departure_iso=scheduled_departure_iso,
        driver_id=driver["id"],
        vehicle_id=vehicle["id"],
    )
    # Prefill with (actual - logical) dummy CONFIRMED reservations so the
    # run's capacity_remaining is `logical_capacity` at return.
    prefill_count = actual_capacity - logical_capacity
    for _ in range(prefill_count):
        emp = unique_employee_code()
        create_reservation(
            run_sheet["id"], emp,
            stops[0]["id"], stops[-1]["id"],
        )
    if prefill_count > 0:
        # Re-read the run-sheet so capacity_remaining reflects the prefill.
        run_sheet = fetch_run_sheet(run_sheet["id"])
    return {
        "stops": stops,
        "route": route,
        "vehicle": vehicle,
        "driver": driver,
        "run_sheet": run_sheet,
    }


def start_boarding(run_sheet_id: str,
                   headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.start_boarding(
        run_sheet_id, headers or DISP,
    ))


def depart_run_sheet(run_sheet_id: str,
                     headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.depart_run_sheet(
        run_sheet_id, headers or DISP,
    ))


def complete_run_sheet(run_sheet_id: str,
                       headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.complete_run_sheet(
        run_sheet_id, headers or DISP,
    ))


def cancel_run_sheet(run_sheet_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.cancel_run_sheet(run_sheet_id, DISP))


def resume_run_sheet(run_sheet_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.resume_run_sheet(run_sheet_id, DISP))


def report_delay(run_sheet_id: str, cause: str, delay_minutes: int,
                 affected_from_stop_id: str,
                 headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    return get_success_data(api_client.report_delay(
        run_sheet_id,
        report_delay_payload(cause, delay_minutes, affected_from_stop_id),
        headers or DISP,
    ))


# ===========================================================================
# Reservations (PRD §3.6)
# ===========================================================================
def create_reservation(run_sheet_id: str, employee_id: str,
                       boarding_stop_id: str, alighting_stop_id: str,
                       *, payer_mode: str = "SELF_PAY",
                       department_code: Optional[str] = None,
                       headers: Optional[Dict[str, str]] = None,
                       ) -> Dict[str, Any]:
    """Create a reservation. By default uses make_employee_headers so the
    X-User-ID equals the body employee_id; per PRD §2.1 the Employee role's
    X-User-ID 'is carried through to the employee_id field on a new
    reservation and used to scope cancellation and listing.'"""
    h = headers if headers is not None else make_employee_headers(employee_id)
    return get_success_data(api_client.create_reservation(
        run_sheet_id,
        create_reservation_payload(employee_id, boarding_stop_id,
                                   alighting_stop_id,
                                   payer_mode=payer_mode,
                                   department_code=department_code),
        h,
    ))


def cancel_reservation(reservation_id: str, employee_id: str,
                       *, by_dispatcher: bool = False) -> Dict[str, Any]:
    """Cancel a reservation. For Employee-triggered cancel the X-User-ID is
    set equal to the reservation's employee_id; for Dispatcher cancel the
    opaque dispatcher headers are used."""
    headers = DISP if by_dispatcher else make_employee_headers(employee_id)
    return get_success_data(api_client.cancel_reservation(
        reservation_id, headers,
    ))


def check_in_rider(run_sheet_id: str, reservation_id: str,
                   boarded_stop_id: str, *, method: str = "QR",
                   headers: Optional[Dict[str, str]] = None,
                   ) -> Dict[str, Any]:
    return get_success_data(api_client.check_in(
        run_sheet_id,
        check_in_payload(reservation_id, boarded_stop_id, method),
        headers or DISP,
    ))


# ===========================================================================
# Tier 4: Reservation scenarios
# ===========================================================================
def setup_run_with_confirmed_reservation(
        *, payer_mode: str = "SELF_PAY",
        department_code: Optional[str] = None,
        seat_capacity: int = 20,
        peak_windows: Optional[List[List[str]]] = None,
        ) -> Dict[str, Any]:
    """End-to-end: PLANNED run-sheet + one CONFIRMED reservation on it.

    Returns a dict with stops, route, vehicle, driver, run_sheet, employee_id,
    reservation.
    """
    base = setup_planned_run_sheet(seat_capacity=seat_capacity,
                                   peak_windows=peak_windows)
    employee_id = unique_employee_code()
    reservation = create_reservation(
        run_sheet_id=base["run_sheet"]["id"],
        employee_id=employee_id,
        boarding_stop_id=base["stops"][0]["id"],
        alighting_stop_id=base["stops"][-1]["id"],
        payer_mode=payer_mode,
        department_code=department_code,
    )
    return {
        **base,
        "employee_id": employee_id,
        "reservation": reservation,
    }


def setup_run_with_capacity_full_and_waitlist(
        *, seat_capacity: int = 1,
        peak_windows: Optional[List[List[str]]] = None,
        ) -> Dict[str, Any]:
    """A run-sheet with exactly `seat_capacity` *test-owned* CONFIRMED
    reservations occupying all remaining capacity, and one extra WAITLISTED
    reservation at position 1.

    PRD §3.3 constrains a vehicle's seat_capacity to [8, 80]; smaller
    "logical" capacities are realised by delegating to setup_planned_run_sheet
    which prefills dummy reservations so the run's `capacity_remaining`
    equals `seat_capacity` at the moment this helper begins creating its
    test-owned reservations.
    """
    base = setup_planned_run_sheet(seat_capacity=seat_capacity,
                                   peak_windows=peak_windows)
    confirmed: List[Dict[str, Any]] = []
    for _ in range(seat_capacity):
        emp = unique_employee_code()
        r = create_reservation(
            base["run_sheet"]["id"], emp,
            base["stops"][0]["id"], base["stops"][-1]["id"],
        )
        confirmed.append({"employee_id": emp, "reservation": r})
    waitlist_emp = unique_employee_code()
    waitlisted = create_reservation(
        base["run_sheet"]["id"], waitlist_emp,
        base["stops"][0]["id"], base["stops"][-1]["id"],
    )
    # Re-read run-sheet so callers see the post-fill capacity_remaining.
    base["run_sheet"] = fetch_run_sheet(base["run_sheet"]["id"])
    return {
        **base,
        "confirmed": confirmed,
        "waitlist_employee_id": waitlist_emp,
        "waitlisted": waitlisted,
    }


# ===========================================================================
# Tier 5: Bills (PRD §3.8)
# ===========================================================================
def previous_billing_month(now: Optional[datetime] = None) -> str:
    """Return YYYY-MM for the month strictly before `now` (PRD §3.8).

    'billing_month must be strictly before the current UTC month.'
    """
    now = now or get_server_now_dt()
    year = now.year
    month = now.month - 1
    if month == 0:
        month = 12
        year -= 1
    return f"{year:04d}-{month:02d}"


def first_day_of_month_iso(billing_month: str) -> str:
    """Return YYYY-MM-01T08:00:00.000Z for a billing month string."""
    year, mm = billing_month.split("-")
    return f"{year}-{mm}-01T08:00:00.000Z"


def setup_employee_bill_with_completed_reservation(
        *, fare_target_segment_count: int = 5,
        ) -> Dict[str, Any]:
    """Create a fully-realised reservation in a PRIOR month, then build a
    DRAFT EMPLOYEE-scope bill so the test can finalize and observe gross_cents.

    Steps:
      1. Build active route with enough stops to make a 5-segment trip.
      2. Pick a scheduled_departure inside the prior UTC month.
      3. Advance clock to a moment before departure; create reservation.
      4. Advance clock past departure; START_BOARDING -> DEPART -> COMPLETE.
      5. Advance clock into the current month so finalize is permitted.
      6. Create DRAFT bill for prior month, employee scope.

    Returns dict with: route, stops, run_sheet, employee_id, reservation, bill.
    """
    # Set anchor — we want everything in a previous calendar month.
    now = get_server_now_dt()
    prev_month = previous_billing_month(now)
    year, mm = prev_month.split("-")
    sched = f"{year}-{mm}-15T05:00:00.000Z"  # mid-month, off-peak (no peak window match)
    sched_dt = parse_iso(sched)

    # Move clock back to just before scheduled_departure for setup.
    advance_clock_to(iso_z(sched_dt - timedelta(hours=2)))

    # Build stop sequence: 6 stops in a line for 5-segment trip.
    stop_count = fare_target_segment_count + 1
    stops = [create_active_stop_at(0.0, i * 0.05) for i in range(stop_count)]
    route = create_and_publish_route(
        start_stop_id=stops[0]["id"],
        end_stop_id=stops[-1]["id"],
        intermediate_stop_ids=[s["id"] for s in stops[1:-1]],
        peak_windows=[["09:00", "11:00"]],
    )
    vehicle = create_active_vehicle(seat_capacity=20)
    driver = create_active_driver(
        license_expiry_date=iso_z(sched_dt + timedelta(days=365)),
    )
    run_sheet = create_run_sheet(
        route_id=route["id"], scheduled_departure_iso=sched,
        driver_id=driver["id"], vehicle_id=vehicle["id"],
    )

    # Create a reservation; X-User-ID will equal employee_id.
    employee_id = unique_employee_code()
    reservation = create_reservation(
        run_sheet["id"], employee_id,
        stops[0]["id"], stops[-1]["id"],
        payer_mode="SELF_PAY",
    )

    # Walk the run through to COMPLETED. Boarding window is +/- 30 min.
    advance_clock_to(iso_z(sched_dt - timedelta(minutes=5)))
    start_boarding(run_sheet["id"])
    # Need to check in BEFORE depart, otherwise cascade marks NO_SHOW.
    check_in_rider(
        run_sheet["id"], reservation["id"], stops[0]["id"],
        headers=make_driver_headers(driver["id"]),
    )
    advance_clock_to(iso_z(sched_dt + timedelta(minutes=1)))
    depart_run_sheet(run_sheet["id"])
    advance_clock_to(iso_z(sched_dt + timedelta(minutes=20)))
    complete_run_sheet(run_sheet["id"])

    # Advance into the next month so the bill's prior-month finalize is allowed.
    next_year = int(year)
    next_mm = int(mm) + 1
    if next_mm == 13:
        next_mm = 1
        next_year += 1
    advance_clock_to(f"{next_year:04d}-{next_mm:02d}-05T02:00:00.000Z")

    bill = get_success_data(api_client.create_bill(
        create_bill_payload(prev_month, "EMPLOYEE", employee_id), DISP,
    ))

    return {
        "stops": stops,
        "route": route,
        "vehicle": vehicle,
        "driver": driver,
        "run_sheet": run_sheet,
        "employee_id": employee_id,
        "reservation": reservation,
        "billing_month": prev_month,
        "bill": bill,
    }


# ===========================================================================
# Audit-log helpers
# ===========================================================================
def list_all_audit_logs(*, subject_type: Optional[str] = None,
                        event_type: Optional[str] = None,
                        subject_id: Optional[str] = None,
                        ) -> List[Dict[str, Any]]:
    """Walk through pagination collecting every audit-log entry that
    matches the filters. PRD §2.11 declares the audit log."""
    out: List[Dict[str, Any]] = []
    offset = 0
    limit = 100
    while True:
        params: Dict[str, Any] = {"limit": limit, "offset": offset}
        if subject_type:
            params["subject_type"] = subject_type
        if event_type:
            params["event_type"] = event_type
        if subject_id:
            params["subject_id"] = subject_id
        resp = api_client.list_audit_logs(AUD, params=params)
        data, meta = validate_paginated(resp)
        out.extend(data)
        if not meta.get("has_more"):
            break
        offset += limit
        if offset >= 5000:  # safety bound
            break
    return out


def fetch_reservation(reservation_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_reservation(reservation_id, DISP))


def fetch_run_sheet(run_sheet_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_run_sheet(run_sheet_id, DISP))


def fetch_route(route_id: str) -> Dict[str, Any]:
    return get_success_data(api_client.get_route(route_id, DISP))


def fetch_bill(bill_id: str) -> Dict[str, Any]:
    """Read a bill by listing with no filter and locating by id."""
    offset = 0
    limit = 100
    while True:
        resp = api_client.list_bills(DISP, params={"limit": limit, "offset": offset})
        data, meta = validate_paginated(resp)
        for b in data:
            if b.get("id") == bill_id:
                return b
        if not meta.get("has_more"):
            break
        offset += limit
        if offset >= 5000:
            break
    raise AssertionError(f"Bill {bill_id} not found in list endpoint")


__all__ = [
    "DISP", "DISP_ALT", "AUD",
    "advance_clock_to", "get_server_now_iso", "get_server_now_dt",
    "create_draft_stop", "create_active_stop", "create_active_stop_at",
    "create_active_driver",
    "create_active_vehicle", "start_vehicle_maintenance",
    "create_draft_route", "publish_route",
    "create_and_publish_route", "retire_route",
    "setup_two_active_stops", "setup_four_active_stops_in_line",
    "setup_active_route_basic",
    "create_run_sheet", "setup_planned_run_sheet",
    "start_boarding", "depart_run_sheet", "complete_run_sheet",
    "cancel_run_sheet", "resume_run_sheet", "report_delay",
    "create_reservation", "cancel_reservation", "check_in_rider",
    "setup_run_with_confirmed_reservation",
    "setup_run_with_capacity_full_and_waitlist",
    "previous_billing_month", "first_day_of_month_iso",
    "setup_employee_bill_with_completed_reservation",
    "list_all_audit_logs",
    "fetch_reservation", "fetch_run_sheet", "fetch_route", "fetch_bill",
]
