"""Composite setup helpers — multi-step preambles tests can reuse.

The ELD/HOS lifecycle takes many API calls to reach interesting
states: register carrier, register ELD device, register vehicle,
register driver, bind, post a series of duty events, advance clock
across midnight, certify the log. Each fixture composes the lower-
level steps so test bodies focus on the rule under assertion.

IDENTITY THREADING — PRD §2.1:

    "When `X-User-Role` is `Driver`, `X-User-ID` is the `id` of the
    acting `Driver` entity ... ownership checks on any resource that
    references a `Driver` ... compare the resource's `driver_id`
    foreign-key field to `X-User-ID`."

After a Driver is created, fixtures act as that driver by minting
headers via `make_driver_headers(driver["id"])` — never by reusing
the shared TEST_USERS["driver_headers"] placeholder for any
ownership-gated call (bind, unbind, duty-event append, edit, certify,
acknowledge, adverse-conditions declare). The placeholder is reserved
for RBAC / 401 / 404 probes.

CLOCK ANCHORING — PRD §3.10:

    "a `PlatformAdmin` may advance the logical server clock to a
    supplied `to` instant via the test-driving capability."

The logical clock is shared across the test process. Fixtures
advance the clock using PlatformAdmin headers so duty-event
event_time, daily-log certify "before today" check, and exemption
midnight expiry are all driven deterministically by the test, not by
wall-clock racing.

Setup calls use `get_success_data` (a lenient 2xx validator) so a
failed setup surfaces as a "Setup failed" error rather than a
confusing test assertion failure downstream.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
)

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    add_days,
    add_hours,
    add_minutes,
    add_seconds,
    bind_payload,
    clock_advance_payload,
    create_adverse_conditions_payload,
    create_carrier_payload,
    create_driver_payload,
    create_duty_event_payload,
    create_eld_device_payload,
    create_vehicle_payload,
    edit_duty_event_payload,
    iso_utc,
    parse_iso,
    random_cdl,
    random_dot_number,
    random_serial,
    random_suffix,
    random_vin,
)
from .test_users import (
    TEST_USERS,
    make_driver_headers,
)


# ===========================================================================
# Clock helpers — PRD §3.10
# ===========================================================================
def get_server_clock_iso() -> str:
    """Read the current logical clock as an ISO 8601 UTC string."""
    h = TEST_USERS["admin_headers"]
    resp = api_client.get_clock(h)
    data = get_success_data(resp)
    if isinstance(data, str):
        return data
    for key in ("now", "clock", "current_time", "server_time", "to"):
        if key in data and isinstance(data[key], str):
            return data[key]
    raise AssertionError(
        f"Could not extract current server clock from {data!r}"
    )


def advance_clock_to_iso(target_iso: str) -> Dict[str, Any]:
    """Advance the logical clock to `target_iso` (PRD §3.10)."""
    h = TEST_USERS["admin_headers"]
    payload = clock_advance_payload(to=target_iso)
    resp = api_client.clock_advance(payload, h)
    return get_success_data(resp)


def advance_clock_by_seconds(seconds: int) -> str:
    current = get_server_clock_iso()
    new_iso = add_seconds(current, seconds)
    advance_clock_to_iso(new_iso)
    return new_iso


def advance_clock_by_minutes(minutes: int) -> str:
    current = get_server_clock_iso()
    new_iso = add_minutes(current, minutes)
    advance_clock_to_iso(new_iso)
    return new_iso


def advance_clock_by_hours(hours: int) -> str:
    current = get_server_clock_iso()
    new_iso = add_hours(current, hours)
    advance_clock_to_iso(new_iso)
    return new_iso


def advance_clock_by_days(days: int) -> str:
    current = get_server_clock_iso()
    new_iso = add_days(current, days)
    advance_clock_to_iso(new_iso)
    return new_iso


# ===========================================================================
# Tier 1 — simple entity creation
# ===========================================================================
def create_carrier(**overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: PlatformAdmin registers a motor carrier."""
    payload = create_carrier_payload(**overrides)
    resp = api_client.create_carrier(payload, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def create_eld_device(*, certified_for_fmcsa: Optional[bool] = None,
                      **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: PlatformAdmin registers an ELD device."""
    payload = create_eld_device_payload(
        certified_for_fmcsa=certified_for_fmcsa, **overrides,
    )
    resp = api_client.create_eld_device(payload, TEST_USERS["admin_headers"])
    return get_success_data(resp)


def create_vehicle(*, carrier_id: str, eld_device_id: str,
                   **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: CarrierSafetyOfficer registers a vehicle."""
    payload = create_vehicle_payload(
        carrier_id=carrier_id, eld_device_id=eld_device_id, **overrides,
    )
    resp = api_client.create_vehicle(payload, TEST_USERS["officer_headers"])
    return get_success_data(resp)


def create_driver(*, carrier_id: str,
                  cycle_type: Optional[str] = None,
                  home_terminal_timezone: Optional[str] = None,
                  **overrides: Any) -> Dict[str, Any]:
    """PRD §3.1: CarrierSafetyOfficer enrolls a driver."""
    payload = create_driver_payload(
        carrier_id=carrier_id,
        cycle_type=cycle_type,
        home_terminal_timezone=home_terminal_timezone,
        **overrides,
    )
    resp = api_client.create_driver(payload, TEST_USERS["officer_headers"])
    return get_success_data(resp)


# ===========================================================================
# Tier 2 — bind / unbind shortcuts
# ===========================================================================
def bind_driver_to_vehicle(driver: Dict[str, Any],
                           vehicle: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.2: Driver binds to a vehicle. Acts as the driver."""
    payload = bind_payload(vehicle_id=vehicle["id"])
    resp = api_client.bind_driver(
        driver["id"], payload, make_driver_headers(driver["id"]),
    )
    return get_success_data(resp)


def unbind_driver(driver: Dict[str, Any]) -> Dict[str, Any]:
    """PRD §3.2: Driver unbinds from current vehicle. Acts as driver."""
    resp = api_client.unbind_driver(
        driver["id"], make_driver_headers(driver["id"]),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 3 — full carrier+vehicle+driver+bind setup
# ===========================================================================
def setup_full_stack(
    *,
    cycle_type: str = "SEVENTY_HOUR_EIGHT_DAY",
    home_terminal_timezone: str = "UTC",
    certified_for_fmcsa: bool = True,
    clock_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Carrier + ELD device + Vehicle + Driver + bind.

    If clock_iso is provided, the server clock is advanced to that
    instant before any other state is built. Returns a dict with
    {carrier, device, vehicle, driver}.
    """
    if clock_iso is not None:
        advance_clock_to_iso(clock_iso)
    carrier = create_carrier()
    device = create_eld_device(certified_for_fmcsa=certified_for_fmcsa)
    vehicle = create_vehicle(
        carrier_id=carrier["id"], eld_device_id=device["id"],
    )
    driver = create_driver(
        carrier_id=carrier["id"],
        cycle_type=cycle_type,
        home_terminal_timezone=home_terminal_timezone,
    )
    driver = bind_driver_to_vehicle(driver, vehicle)
    return {
        "carrier": carrier,
        "device": device,
        "vehicle": vehicle,
        "driver": driver,
    }


def setup_unbound_driver_and_vehicle(
    *,
    home_terminal_timezone: str = "UTC",
    certified_for_fmcsa: bool = True,
    clock_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Carrier + ELD device + Vehicle + Driver (NOT bound).

    Use for tests that probe bind preconditions or duty events on
    unbound drivers (ERR_DRIVER_NOT_BOUND).
    """
    if clock_iso is not None:
        advance_clock_to_iso(clock_iso)
    carrier = create_carrier()
    device = create_eld_device(certified_for_fmcsa=certified_for_fmcsa)
    vehicle = create_vehicle(
        carrier_id=carrier["id"], eld_device_id=device["id"],
    )
    driver = create_driver(
        carrier_id=carrier["id"],
        home_terminal_timezone=home_terminal_timezone,
    )
    return {
        "carrier": carrier,
        "device": device,
        "vehicle": vehicle,
        "driver": driver,
    }


# ===========================================================================
# Tier 4 — duty event helpers and recipes
# ===========================================================================
def post_duty_event(driver: Dict[str, Any], *,
                    new_status: str,
                    event_time: str,
                    vehicle_id: Optional[str] = None,
                    latitude: Optional[float] = None,
                    longitude: Optional[float] = None,
                    odometer_miles: Optional[float] = None,
                    annotation: Optional[str] = None,
                    adverse_conditions_exemption_id: Optional[str] = None,
                    expect_success: bool = True,
                    ) -> Any:
    """Append a duty event acting as the driver. By default expects
    a 2xx; pass expect_success=False to return the raw response so
    the caller can inspect a failure path."""
    payload = create_duty_event_payload(
        new_status=new_status,
        event_time=event_time,
        latitude=latitude,
        longitude=longitude,
        vehicle_id=vehicle_id,
        odometer_miles=odometer_miles,
        annotation=annotation,
        adverse_conditions_exemption_id=adverse_conditions_exemption_id,
    )
    resp = api_client.create_duty_event(
        driver["id"], payload, make_driver_headers(driver["id"]),
    )
    if expect_success:
        return get_success_data(resp)
    return resp


def get_driver(driver_id: str) -> Dict[str, Any]:
    h = TEST_USERS["officer_headers"]
    return get_success_data(api_client.get_driver(driver_id, h))


def get_vehicle(vehicle_id: str) -> Dict[str, Any]:
    h = TEST_USERS["officer_headers"]
    return get_success_data(api_client.get_vehicle(vehicle_id, h))


def get_violation(violation_id: str) -> Dict[str, Any]:
    h = TEST_USERS["officer_headers"]
    return get_success_data(api_client.get_violation(violation_id, h))


def get_daily_log(driver: Dict[str, Any], log_id: str) -> Dict[str, Any]:
    return get_success_data(
        api_client.get_daily_log(
            driver["id"], log_id, make_driver_headers(driver["id"]),
        )
    )


def list_daily_logs(driver: Dict[str, Any],
                    params: Optional[Dict[str, Any]] = None,
                    ) -> List[Dict[str, Any]]:
    """List a driver's daily logs across all pages."""
    h = make_driver_headers(driver["id"])
    all_logs: List[Dict[str, Any]] = []
    offset = 0
    page = dict(params or {})
    page.setdefault("limit", 100)
    while True:
        page["offset"] = offset
        resp = api_client.list_daily_logs(driver["id"], h, params=page)
        items, meta = validate_paginated(resp)
        all_logs.extend(items)
        if not meta.get("has_more"):
            break
        offset += page["limit"]
    return all_logs


def list_duty_events(driver: Dict[str, Any],
                     params: Optional[Dict[str, Any]] = None,
                     ) -> List[Dict[str, Any]]:
    h = make_driver_headers(driver["id"])
    all_events: List[Dict[str, Any]] = []
    offset = 0
    page = dict(params or {})
    page.setdefault("limit", 100)
    while True:
        page["offset"] = offset
        resp = api_client.list_duty_events(driver["id"], h, params=page)
        items, meta = validate_paginated(resp)
        all_events.extend(items)
        if not meta.get("has_more"):
            break
        offset += page["limit"]
    return all_events


def list_violations(params: Optional[Dict[str, Any]] = None,
                    ) -> List[Dict[str, Any]]:
    h = TEST_USERS["officer_headers"]
    all_v: List[Dict[str, Any]] = []
    offset = 0
    page = dict(params or {})
    page.setdefault("limit", 100)
    while True:
        page["offset"] = offset
        resp = api_client.list_violations(h, params=page)
        items, meta = validate_paginated(resp)
        all_v.extend(items)
        if not meta.get("has_more"):
            break
        offset += page["limit"]
    return all_v


def get_hos_snapshot(driver: Dict[str, Any]) -> Dict[str, Any]:
    h = make_driver_headers(driver["id"])
    return get_success_data(api_client.get_hos_snapshot(driver["id"], h))


# ===========================================================================
# Tier 4 — accumulating duty-event sequences
# ===========================================================================
def setup_after_10h_break(
    *,
    cycle_type: str = "SEVENTY_HOUR_EIGHT_DAY",
    home_terminal_timezone: str = "UTC",
    break_end_iso: str,
) -> Dict[str, Any]:
    """Carrier+vehicle+driver+bound; OFF_DUTY through SLEEPER_BERTH to
    complete a 10h qualifying break ending at `break_end_iso`.

    Sequence (relative to break_end - 10h):
      - clock advanced to break_start
      - POST OFF_DUTY at break_start (without vehicle_id: per PRD §3.3
        OFF_DUTY does not require a vehicle, but driver is bound so
        we omit vehicle_id only when permitted; we include it when
        needed for monotonic odometer threading). Actually we keep
        it OFF — the driver is bound to a vehicle but the OFF_DUTY
        and SLEEPER_BERTH events do not require vehicle_id per the
        PRD §3.3 list of statuses that require it.
      - POST SLEEPER_BERTH at break_start (closes 10h reset window).
    Then clock advances to break_end.

    Returns {carrier, device, vehicle, driver}.
    """
    # We want the qualifying break to END at break_end_iso such that any
    # DRIVING attempt at break_end_iso + 1s (per downstream recipes) finds
    # a continuous OFF_DUTY+SLEEPER_BERTH window of >= 600 minutes. To
    # achieve that we start the rest 60 seconds before break_end - 10h
    # (giving 600m + 60s of continuous rest by the time of the next
    # write at break_end + 1s).
    rest_start = add_seconds(add_hours(break_end_iso, -10), -60)
    advance_clock_to_iso(rest_start)
    state = setup_full_stack(
        cycle_type=cycle_type,
        home_terminal_timezone=home_terminal_timezone,
    )
    driver = state["driver"]
    # OFF_DUTY at rest_start.
    post_duty_event(
        driver,
        new_status="OFF_DUTY",
        event_time=rest_start,
    )
    # SLEEPER_BERTH at rest_start + 1s — continuous off+sleeper accrual.
    # Then we wait the full 10h+ via clock advance.
    post_duty_event(
        driver,
        new_status="SLEEPER_BERTH",
        event_time=add_seconds(rest_start, 1),
    )
    advance_clock_to_iso(break_end_iso)
    return state


def drive_minutes(driver: Dict[str, Any], vehicle: Dict[str, Any],
                  *, start_iso: str, minutes: int,
                  start_odometer: float = 1000.0,
                  ) -> Tuple[Dict[str, Any], str]:
    """Post a DRIVING event at start_iso and an OFF_DUTY (or
    ON_DUTY_NOT_DRIVING) event at start_iso + minutes to close the
    driving interval at exactly `minutes`. Returns the closing event
    and its event_time."""
    drive_evt = post_duty_event(
        driver, new_status="DRIVING", event_time=start_iso,
        vehicle_id=vehicle["id"], odometer_miles=start_odometer,
    )
    end_iso = add_minutes(start_iso, minutes)
    close_evt = post_duty_event(
        driver, new_status="ON_DUTY_NOT_DRIVING",
        event_time=end_iso, vehicle_id=vehicle["id"],
        odometer_miles=start_odometer + 50.0,
    )
    return close_evt, end_iso


def post_off_duty(driver: Dict[str, Any], *, event_time: str,
                  ) -> Dict[str, Any]:
    return post_duty_event(
        driver, new_status="OFF_DUTY", event_time=event_time,
    )


def post_sleeper(driver: Dict[str, Any], *, event_time: str,
                 ) -> Dict[str, Any]:
    return post_duty_event(
        driver, new_status="SLEEPER_BERTH", event_time=event_time,
    )


def post_driving(driver: Dict[str, Any], vehicle: Dict[str, Any], *,
                 event_time: str, odometer_miles: Optional[float] = None,
                 adverse_conditions_exemption_id: Optional[str] = None,
                 ) -> Any:
    return post_duty_event(
        driver, new_status="DRIVING", event_time=event_time,
        vehicle_id=vehicle["id"], odometer_miles=odometer_miles,
        adverse_conditions_exemption_id=adverse_conditions_exemption_id,
    )


# ===========================================================================
# Tier 4 — pinned-state recipes for difficulty-design tests
# ===========================================================================
def setup_driving_at_exact_660_minutes(
    *,
    break_end_iso: str = "2026-05-20T10:00:00.000Z",
) -> Dict[str, Any]:
    """Reach a state where the driver has driven exactly 660 minutes
    since the last 10h qualifying break — boundary fixture for the
    11-hour limit.

    Sequence (per difficulty-design recipe):
      - 10h break ends at break_end_iso
      - DRIVING at break_end_iso
      - ON_DUTY_NOT_DRIVING at break_end_iso + 660m (closes DRIVING at
        exactly 660 minutes)
    Returns {carrier, device, vehicle, driver, driving_event,
             close_event, last_event_time}.
    """
    state = setup_after_10h_break(break_end_iso=break_end_iso)
    driver, vehicle = state["driver"], state["vehicle"]
    driving_evt = post_driving(
        driver, vehicle,
        event_time=add_seconds(break_end_iso, 1),
        odometer_miles=1000.0,
    )
    close_iso = add_seconds(add_minutes(break_end_iso, 660), 1)
    close_evt = post_duty_event(
        driver, new_status="ON_DUTY_NOT_DRIVING",
        event_time=close_iso, vehicle_id=vehicle["id"],
        odometer_miles=1500.0,
    )
    return {
        **state,
        "driving_event": driving_evt,
        "close_event": close_evt,
        "break_end_iso": break_end_iso,
        "last_event_time": close_iso,
    }


def setup_driving_at_exact_745_minutes(
    *,
    break_end_iso: str = "2026-05-15T10:00:00.000Z",
) -> Dict[str, Any]:
    """Reach the state where a closing OFF_DUTY event will detect an
    85-minute overage on the 11-hour limit (driving_minutes_since_break
    == 745).

    Sequence (per difficulty-design recipe for transitive_cascade):
      - 10h break ends at break_end_iso
      - DRIVING at break_end_iso
      - OFF_DUTY at break_end_iso + 745m  ← triggers Violation creation
    Returns {carrier, device, vehicle, driver, driving_event,
             closing_event, log_date, last_event_time}.
    """
    state = setup_after_10h_break(break_end_iso=break_end_iso)
    driver, vehicle = state["driver"], state["vehicle"]
    drive_start = add_seconds(break_end_iso, 1)
    driving_evt = post_driving(
        driver, vehicle,
        event_time=drive_start,
        odometer_miles=2000.0,
    )
    # Close DRIVING exactly 745 minutes after the DRIVING event so the
    # driving_minutes_since_break value equals 745 (and overage = 85).
    close_iso = add_minutes(drive_start, 745)
    # Now advance clock past close_iso so the duty event is valid in time.
    advance_clock_to_iso(add_seconds(close_iso, 60))
    closing_evt = post_duty_event(
        driver, new_status="OFF_DUTY",
        event_time=close_iso,
    )
    log_date = close_iso[:10]
    return {
        **state,
        "driving_event": driving_evt,
        "closing_event": closing_evt,
        "log_date": log_date,
        "last_event_time": close_iso,
    }


def setup_violation_from_overage(
    *,
    break_end_iso: str = "2026-05-15T10:00:00.000Z",
) -> Dict[str, Any]:
    """Build the 745-minute overage scenario, then locate the
    Violation row created as a side effect. Returns the
    setup_driving_at_exact_745_minutes payload plus the Violation."""
    state = setup_driving_at_exact_745_minutes(break_end_iso=break_end_iso)
    # Locate the Violation for this driver.
    vios = list_violations(params={"driver_id": state["driver"]["id"]})
    assert len(vios) >= 1, (
        "Setup failed: expected at least one Violation after 745-minute "
        f"overage, found {len(vios)} for driver {state['driver']['id']}"
    )
    # Pick the one that points at the closing event.
    violation = None
    for v in vios:
        if v.get("triggering_duty_event_id") == state["closing_event"]["id"]:
            violation = v
            break
    if violation is None:
        # Fallback: use the most recent (highest created_at) for the driver.
        violation = sorted(
            vios, key=lambda v: v.get("created_at", ""),
        )[-1]
    return {**state, "violation": violation}


# ===========================================================================
# Tier 4 — sleeper-berth pair fixture
# ===========================================================================
def setup_sleeper_berth_pair_eight_two(
    *,
    anchor_iso: str = "2026-05-10T00:00:00.000Z",
) -> Dict[str, Any]:
    """Build an 8-2 sleeper-berth split per PRD §3.5:
      - OFF_DUTY at anchor (forms the 120-minute "short leg" L2)
      - SLEEPER_BERTH at anchor + 120m
      - 480 minutes of SLEEPER_BERTH (forms the 480-minute "long leg" L1)
      - clock advanced to anchor + 600m, then a DRIVING event is
        attempted by the test.
    Returns {carrier, device, vehicle, driver, drive_iso}.
    """
    advance_clock_to_iso(anchor_iso)
    state = setup_full_stack(cycle_type="SEVENTY_HOUR_EIGHT_DAY",
                             home_terminal_timezone="UTC")
    driver = state["driver"]
    # OFF_DUTY at anchor + 1s — start of L2.
    post_duty_event(driver, new_status="OFF_DUTY",
                    event_time=add_seconds(anchor_iso, 1))
    # SLEEPER_BERTH at anchor + 120m — end of L2, start of L1.
    sb_iso = add_minutes(anchor_iso, 120)
    post_duty_event(driver, new_status="SLEEPER_BERTH",
                    event_time=add_seconds(sb_iso, 1))
    # Advance clock to anchor + 120m + 480m == anchor + 600m so a
    # DRIVING attempt happens at the end of the long leg.
    drive_iso = add_minutes(anchor_iso, 600)
    advance_clock_to_iso(drive_iso)
    return {**state, "drive_iso": drive_iso, "long_leg_end": drive_iso}


# ===========================================================================
# Tier 5 — daily log certification and edit recipes
# ===========================================================================
def certify_log(driver: Dict[str, Any], log_id: str) -> Dict[str, Any]:
    resp = api_client.certify_daily_log(
        driver["id"], log_id, make_driver_headers(driver["id"]),
    )
    return get_success_data(resp)


def find_log_for_date(driver: Dict[str, Any], log_date: str,
                      ) -> Optional[Dict[str, Any]]:
    for log in list_daily_logs(driver):
        if log.get("log_date") == log_date:
            return log
    return None


def setup_certified_log(
    *,
    log_date: str = "2026-05-09",
    home_terminal_timezone: str = "UTC",
) -> Dict[str, Any]:
    """Post three ACTIVE events on log_date, advance clock to the
    next day, certify the log. Returns
    {carrier, device, vehicle, driver, log, events:[..]}.
    """
    # Start clock at log_date 00:00 so all events fall on log_date.
    log_start_iso = f"{log_date}T00:00:00.000Z"
    advance_clock_to_iso(log_start_iso)
    state = setup_full_stack(
        cycle_type="SEVENTY_HOUR_EIGHT_DAY",
        home_terminal_timezone=home_terminal_timezone,
    )
    driver, vehicle = state["driver"], state["vehicle"]
    # Event at 09:00, 12:00, 15:00 UTC.
    e1 = post_duty_event(
        driver, new_status="ON_DUTY_NOT_DRIVING",
        event_time=f"{log_date}T09:00:00.000Z",
        vehicle_id=vehicle["id"], odometer_miles=1000.0,
        annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
    )
    e2 = post_duty_event(
        driver, new_status="DRIVING",
        event_time=f"{log_date}T12:00:00.000Z",
        vehicle_id=vehicle["id"], odometer_miles=1100.0,
    )
    e3 = post_duty_event(
        driver, new_status="OFF_DUTY",
        event_time=f"{log_date}T15:00:00.000Z",
    )
    # Advance to next day so log_date < today.
    next_day_iso = add_days(log_start_iso, 1)
    advance_clock_to_iso(next_day_iso)
    log = find_log_for_date(driver, log_date)
    assert log is not None, (
        f"Setup failed: no DailyLog for {log_date} on driver "
        f"{driver['id']}"
    )
    log = certify_log(driver, log["id"])
    return {**state, "log": log, "events": [e1, e2, e3]}


def setup_log_at_midnight_boundary(
    *,
    log_date: str = "2026-05-20",
    home_terminal_timezone: str = "UTC",
) -> Dict[str, Any]:
    """Build a DailyLog for `log_date` with one ACTIVE event, and
    leave the clock at the last second of `log_date` so a certify
    attempt is rejected with ERR_LOG_NOT_YET_CERTIFIABLE (boundary
    test for the "strictly less than today" rule).

    Returns {carrier, device, vehicle, driver, log}.
    """
    log_start_iso = f"{log_date}T00:00:00.000Z"
    advance_clock_to_iso(log_start_iso)
    state = setup_full_stack(home_terminal_timezone=home_terminal_timezone)
    driver, vehicle = state["driver"], state["vehicle"]
    # One ACTIVE event at 09:00 on log_date.
    post_duty_event(
        driver, new_status="ON_DUTY_NOT_DRIVING",
        event_time=f"{log_date}T09:00:00.000Z",
        vehicle_id=vehicle["id"], odometer_miles=1000.0,
        annotation=TEST_DEFAULTS["DEFAULT_ANNOTATION"],
    )
    # Advance clock to log_date 23:59:59 — still log_date in UTC.
    end_of_day = f"{log_date}T23:59:59.000Z"
    advance_clock_to_iso(end_of_day)
    log = find_log_for_date(driver, log_date)
    assert log is not None, (
        f"Setup failed: no DailyLog for {log_date}"
    )
    return {**state, "log": log, "boundary_iso": end_of_day}


# ===========================================================================
# Tier 5 — adverse-conditions exemption recipe
# ===========================================================================
def declare_adverse_conditions(driver: Dict[str, Any],
                               declared_at: str,
                               reason: Optional[str] = None,
                               ) -> Dict[str, Any]:
    payload = create_adverse_conditions_payload(
        declared_at=declared_at, reason=reason,
    )
    resp = api_client.create_adverse_conditions(
        driver["id"], payload, make_driver_headers(driver["id"]),
    )
    return get_success_data(resp)


# ===========================================================================
# Tier 5 — violation lifecycle helpers
# ===========================================================================
def acknowledge_violation(driver: Dict[str, Any],
                          violation_id: str) -> Dict[str, Any]:
    resp = api_client.acknowledge_violation(
        violation_id, make_driver_headers(driver["id"]),
    )
    return get_success_data(resp)


def report_violation(violation_id: str,
                     officer_headers: Optional[Dict[str, str]] = None,
                     ) -> Dict[str, Any]:
    h = officer_headers or TEST_USERS["officer_headers"]
    resp = api_client.report_violation_to_fmcsa(violation_id, h)
    return get_success_data(resp)


# ===========================================================================
# Tier 5 — duty-event edit helper
# ===========================================================================
def edit_duty_event(driver: Dict[str, Any], event_id: str,
                    **overrides: Any) -> Dict[str, Any]:
    payload = edit_duty_event_payload(**overrides)
    resp = api_client.edit_duty_event(
        driver["id"], event_id, payload, make_driver_headers(driver["id"]),
    )
    return get_success_data(resp)


__all__ = [
    # Clock
    "get_server_clock_iso", "advance_clock_to_iso",
    "advance_clock_by_seconds", "advance_clock_by_minutes",
    "advance_clock_by_hours", "advance_clock_by_days",
    # Tier 1
    "create_carrier", "create_eld_device",
    "create_vehicle", "create_driver",
    # Tier 2
    "bind_driver_to_vehicle", "unbind_driver",
    # Tier 3
    "setup_full_stack", "setup_unbound_driver_and_vehicle",
    # Tier 4 — helpers
    "post_duty_event", "post_off_duty", "post_sleeper", "post_driving",
    "drive_minutes",
    "get_driver", "get_vehicle", "get_violation",
    "get_daily_log", "list_daily_logs", "list_duty_events",
    "list_violations", "get_hos_snapshot",
    # Tier 4 — pinned recipes
    "setup_after_10h_break",
    "setup_driving_at_exact_660_minutes",
    "setup_driving_at_exact_745_minutes",
    "setup_violation_from_overage",
    "setup_sleeper_berth_pair_eight_two",
    # Tier 5
    "certify_log", "find_log_for_date",
    "setup_certified_log", "setup_log_at_midnight_boundary",
    "declare_adverse_conditions",
    "acknowledge_violation", "report_violation",
    "edit_duty_event",
]
