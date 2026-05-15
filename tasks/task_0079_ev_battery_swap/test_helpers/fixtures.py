"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() from the framework (lenient validator) so setup
failures produce clear "Setup failed" errors instead of confusing
assertion failures.

All fixtures honor PRD §2.1 identity rules:

- Member is entity_backed → ownership-gated Member calls MUST use
  make_member_headers(member['id']).
- StationOperator is entity_backed on Station → operator calls MUST use
  make_operator_headers(station['id']).
- PlatformAdmin is opaque → shared TEST_USERS['platform_admin_headers']
  is canonical.

The helpers below build up to a full swap workflow precondition step
by step; each test composes only the helpers it needs.
"""
from __future__ import annotations
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    RESERVATION_LEAD_MINUTES,
    RESERVATION_SLOT_MINUTES,
)
from .factories import (
    clock_advance_payload,
    create_battery_model_payload,
    create_battery_payload,
    create_charging_slot_payload,
    create_compatibility_rule_payload,
    create_dispatch_order_payload,
    create_member_payload,
    create_reservation_payload,
    create_station_payload,
    create_vehicle_model_payload,
    create_vehicle_payload,
    create_walk_in_payload,
    finish_charging_payload,
    inspect_payload,
    install_payload,
    refund_payload,
    report_fault_payload,
    start_charging_payload,
)
from .test_users import (
    TEST_USERS,
    make_member_headers,
    make_operator_headers,
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def now_iso() -> str:
    """Current server time as ISO 8601 UTC with milliseconds.

    Tests that depend on temporal validations should call advance_clock()
    first to pin a deterministic server clock, then derive slot
    timestamps from that pinned instant.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def iso_plus(base_iso: str, minutes: int = 0,
             seconds: int = 0, hours: int = 0) -> str:
    """Add a delta to an ISO 8601 timestamp and return ISO 8601 UTC ms."""
    base = datetime.fromisoformat(base_iso.replace("Z", "+00:00"))
    out = base + timedelta(minutes=minutes, seconds=seconds, hours=hours)
    out = out.astimezone(timezone.utc)
    return out.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{out.microsecond // 1000:03d}Z"
    )


def advance_clock_to(to_iso: str) -> None:
    """Move the server's logical clock forward to to_iso (PRD §3.8)."""
    resp = api_client.advance_clock(
        clock_advance_payload(to_iso),
        TEST_USERS["platform_admin_headers"],
    )
    get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 1: Single-entity create helpers
# ---------------------------------------------------------------------------
def create_station(*, total_slots: int = 4, name: Optional[str] = None,
                   latitude: float = 30.0,
                   longitude: float = 120.0) -> Dict[str, Any]:
    """Create a Station via PlatformAdmin."""
    payload = create_station_payload(
        total_slots=total_slots, latitude=latitude, longitude=longitude,
    )
    if name is not None:
        payload["name"] = name
    resp = api_client.create_station(
        payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def add_charging_slot(station_id: str, slot_number: int,
                      tou_zone: Optional[str] = None) -> Dict[str, Any]:
    """Add a ChargingSlot to a station via PlatformAdmin."""
    payload = create_charging_slot_payload(
        slot_number=slot_number, tou_zone=tou_zone,
    )
    resp = api_client.create_charging_slot(
        station_id, payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def create_battery_model(*, code: Optional[str] = None,
                         rated_capacity_kwh: float = 50.0,
                         ev_soh_floor_pct: Optional[float] = None,
                         **overrides: Any) -> Dict[str, Any]:
    """Create a BatteryModel."""
    payload = create_battery_model_payload(
        rated_capacity_kwh=rated_capacity_kwh,
        **overrides,
    )
    if code is not None:
        payload["code"] = code
    if ev_soh_floor_pct is not None:
        payload["ev_soh_floor_pct"] = ev_soh_floor_pct
    resp = api_client.create_battery_model(
        payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def create_vehicle_model(*, code: Optional[str] = None,
                         **overrides: Any) -> Dict[str, Any]:
    payload = create_vehicle_model_payload(**overrides)
    if code is not None:
        payload["code"] = code
    resp = api_client.create_vehicle_model(
        payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def create_compatibility(vehicle_model_code: str,
                         battery_model_code: str,
                         *, connector_match: bool = True,
                         bms_handshake_supported: bool = True,
                         ) -> Dict[str, Any]:
    payload = create_compatibility_rule_payload(
        vehicle_model_code=vehicle_model_code,
        battery_model_code=battery_model_code,
        connector_match=connector_match,
        bms_handshake_supported=bms_handshake_supported,
    )
    resp = api_client.create_compatibility_rule(
        payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def create_battery(*, station_id: str, battery_model_code: str,
                   soc_pct: Optional[float] = None,
                   soh_pct: Optional[float] = None,
                   serial_number: Optional[str] = None,
                   **overrides: Any) -> Dict[str, Any]:
    payload = create_battery_payload(
        battery_model_code=battery_model_code,
        station_id=station_id,
        **overrides,
    )
    if soc_pct is not None:
        payload["soc_pct"] = soc_pct
    if soh_pct is not None:
        payload["soh_pct"] = soh_pct
    if serial_number is not None:
        payload["serial_number"] = serial_number
    resp = api_client.create_battery(
        payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def create_member(*, subscription_tier: Optional[str] = None,
                  subscription_swaps_remaining: Optional[int] = None,
                  name: Optional[str] = None,
                  phone: Optional[str] = None,
                  **overrides: Any) -> Dict[str, Any]:
    payload = create_member_payload(**overrides)
    if subscription_tier is not None:
        payload["subscription_tier"] = subscription_tier
    if subscription_swaps_remaining is not None:
        payload["subscription_swaps_remaining"] = subscription_swaps_remaining
    if name is not None:
        payload["name"] = name
    if phone is not None:
        payload["phone"] = phone
    resp = api_client.create_member(
        payload, TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


def create_vehicle(*, vehicle_model_code: str, owner_member_id: str,
                   installed_battery_id: Optional[str] = None,
                   vin: Optional[str] = None,
                   **overrides: Any) -> Dict[str, Any]:
    """Create a Vehicle via the owning Member (ownership-gated via
    Member.id == X-User-ID per PRD §2.1)."""
    payload = create_vehicle_payload(
        vehicle_model_code=vehicle_model_code,
        owner_member_id=owner_member_id,
        **overrides,
    )
    if installed_battery_id is not None:
        payload["installed_battery_id"] = installed_battery_id
    if vin is not None:
        payload["vin"] = vin
    resp = api_client.create_vehicle(
        payload, make_member_headers(owner_member_id),
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 2: Composite scenes
# ---------------------------------------------------------------------------
def setup_models_and_compat(
    *,
    rated_capacity_kwh: float = 50.0,
    ev_soh_floor_pct: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Create one BatteryModel and one VehicleModel with a compatibility
    rule that has connector_match=true and bms_handshake_supported=true."""
    bm = create_battery_model(
        rated_capacity_kwh=rated_capacity_kwh,
        ev_soh_floor_pct=ev_soh_floor_pct,
    )
    vm = create_vehicle_model()
    create_compatibility(vm["code"], bm["code"])
    return bm, vm


def setup_basic_scene(
    *,
    total_slots: int = 4,
    num_idle_batteries: int = 1,
    rated_capacity_kwh: float = 50.0,
    ev_soh_floor_pct: Optional[float] = None,
    tou_zone: str = "SHOULDER",
    member_subscription_tier: Optional[str] = None,
    member_subscription_swaps_remaining: Optional[int] = None,
    member_existing_installed: bool = True,
) -> Dict[str, Any]:
    """Create a complete swap-ready scenario.

    Produces:
      - 1 Station with `total_slots` slots (all SHOULDER unless overridden
        via tou_zone — first slot uses tou_zone, rest default to SHOULDER)
      - BatteryModel BM, VehicleModel VM, CompatibilityRule(VM, BM)
      - Member, Vehicle owned by Member.
      - num_idle_batteries IDLE batteries at the station, all of model BM.
      - If member_existing_installed=True: also create an additional IDLE
        battery at the station marked as the vehicle's installed_battery_id
        (status IN_USE via vehicle creation flow).
    Returns: dict with keys station, slots, battery_model, vehicle_model,
             member, vehicle, idle_batteries, outgoing_battery (optional).
    """
    station = create_station(total_slots=total_slots)
    slots: List[Dict[str, Any]] = []
    for i in range(1, total_slots + 1):
        zone = tou_zone if i == 1 else "SHOULDER"
        slots.append(add_charging_slot(station["id"], i, tou_zone=zone))

    bm, vm = setup_models_and_compat(
        rated_capacity_kwh=rated_capacity_kwh,
        ev_soh_floor_pct=ev_soh_floor_pct,
    )

    member = create_member(
        subscription_tier=member_subscription_tier,
        subscription_swaps_remaining=member_subscription_swaps_remaining,
    )

    # Build idle batteries FIRST so they have the earliest created_at;
    # the eligibility filter in PRD §3.3 ranks by soh_pct DESC, then
    # cycle_count ASC, then created_at ASC, then id ASC. If we created
    # the outgoing battery before the held candidates and all batteries
    # carried the same default soh_pct/cycle_count, the outgoing battery
    # (registered earlier) would outrank the held candidates on the
    # created_at tie-break and accidentally be chosen as held — defeating
    # any test that needs a specific held battery. Creating the held
    # candidates first makes them deterministically preferred regardless
    # of soh_pct equality.
    idle_batteries = []
    for _ in range(num_idle_batteries):
        idle_batteries.append(
            create_battery(
                station_id=station["id"],
                battery_model_code=bm["code"],
                soc_pct=80.0,
            )
        )

    # Now build the vehicle; if requested, mint an outgoing battery and
    # attach it via Vehicle.installed_battery_id at creation. The outgoing
    # battery is registered LAST (later created_at) AND given a lower
    # soh_pct (85, grade B but still above the default ev_soh_floor of 80
    # so it is not auto-retired). Both safeguards ensure the eligibility
    # filter described in PRD §3.3 never picks the outgoing battery as
    # held: ranked by soh_pct DESC, the held candidates (soh 100) always
    # outrank the outgoing (soh 85). PRD §3.3 says the held selection
    # filter includes status=IDLE and station_id matching and does NOT
    # exclude batteries that are referenced by a Vehicle.installed_
    # battery_id, so a PRD-faithful implementation that leaves the
    # outgoing at status=IDLE would otherwise allow the outgoing to be
    # held — which is undesirable for these tests.
    outgoing: Optional[Dict[str, Any]] = None
    if member_existing_installed:
        outgoing = create_battery(
            station_id=station["id"], battery_model_code=bm["code"],
            soc_pct=20.0, soh_pct=85.0,
        )
        vehicle = create_vehicle(
            vehicle_model_code=vm["code"],
            owner_member_id=member["id"],
            installed_battery_id=outgoing["id"],
        )
    else:
        vehicle = create_vehicle(
            vehicle_model_code=vm["code"],
            owner_member_id=member["id"],
        )

    return {
        "station": station,
        "slots": slots,
        "battery_model": bm,
        "vehicle_model": vm,
        "member": member,
        "vehicle": vehicle,
        "idle_batteries": idle_batteries,
        "outgoing_battery": outgoing,
    }


# ---------------------------------------------------------------------------
# Tier 3: Reservation + swap-event lifecycle shortcuts
# ---------------------------------------------------------------------------
def book_reservation(scene: Dict[str, Any],
                     *, lead_minutes: int = 10,
                     ) -> Dict[str, Any]:
    """Book a Reservation for the given scene's Member/Vehicle/Station.

    The slot starts `lead_minutes` minutes from now (must be >= 5 per
    PRD §3.3). The Member's headers are minted with Member.id per PRD §2.1.

    Pins the server clock to wall-clock first so the freshly-derived
    slot timestamps are interpreted against a deterministic "now". Prior
    tests may have advanced the server clock into the future via
    `advance_clock_to`; without this anchor the new slot timestamps
    would read as "in the past" relative to the stale server clock and
    every reservation booked through this helper would fail
    `ERR_INVALID_TIME_SLOT`.
    """
    base = now_iso()
    advance_clock_to(base)
    slot_start = iso_plus(base, minutes=lead_minutes)
    slot_end = iso_plus(slot_start, minutes=RESERVATION_SLOT_MINUTES)
    payload = create_reservation_payload(
        member_id=scene["member"]["id"],
        vehicle_id=scene["vehicle"]["id"],
        station_id=scene["station"]["id"],
        slot_start_at=slot_start,
        slot_end_at=slot_end,
    )
    resp = api_client.create_reservation(
        payload, make_member_headers(scene["member"]["id"]),
    )
    return get_success_data(resp)


def reservation_at(scene: Dict[str, Any], *, slot_start_iso: str,
                   slot_end_iso: Optional[str] = None,
                   member_id: Optional[str] = None,
                   vehicle_id: Optional[str] = None,
                   ) -> Dict[str, Any]:
    """Create a reservation with explicit slot timestamps and (optionally)
    a different member/vehicle than the scene default. Useful for overlap
    tests that need precise boundary times."""
    end_iso = slot_end_iso or iso_plus(
        slot_start_iso, minutes=RESERVATION_SLOT_MINUTES,
    )
    mid = member_id or scene["member"]["id"]
    vid = vehicle_id or scene["vehicle"]["id"]
    payload = create_reservation_payload(
        member_id=mid,
        vehicle_id=vid,
        station_id=scene["station"]["id"],
        slot_start_at=slot_start_iso,
        slot_end_at=end_iso,
    )
    resp = api_client.create_reservation(
        payload, make_member_headers(mid),
    )
    return get_success_data(resp)


def check_in(scene: Dict[str, Any],
             reservation: Dict[str, Any]) -> Dict[str, Any]:
    """Advance time to inside the reservation's slot, then check in.

    PRD §3.4: "current server time lies inside the half-open window
    [slot_start_at, slot_end_at)" — we pin the clock to slot_start +
    1 second so the precondition holds deterministically.
    """
    advance_clock_to(iso_plus(reservation["slot_start_at"], seconds=1))
    resp = api_client.check_in_reservation(
        reservation["id"],
        make_operator_headers(scene["station"]["id"]),
    )
    return get_success_data(resp)


def get_swap_event_for(reservation: Dict[str, Any],
                       scene: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve the SwapEvent created at check-in by listing SwapEvents
    indirectly through GET /reservations/{id} — we read swap_event_id
    via the reservation if exposed, else fall back to a list scan.

    The PRD does not guarantee a swap_event_id field on Reservation;
    we fetch the swap_event id by listing the reservation detail and
    walking back via GET against the swap-event endpoint. As a robust
    fallback the caller can pass through the swap_event id from a
    direct response of the check-in flow.
    """
    # Most implementations expose either:
    #   reservation["swap_event_id"] (denormalized) OR
    # The PRD doesn't pin a list endpoint that filters swap-events by
    # reservation_id. So tests should capture the swap-event from the
    # check-in response if available, or call the workflow helpers below
    # which keep a handle through the workflow.
    raise NotImplementedError(
        "use perform_check_in_and_fetch_swap_event instead"
    )


def perform_check_in_and_fetch_swap_event(
    scene: Dict[str, Any], reservation: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Check in and resolve the resulting SwapEvent.

    Strategy: PRD §3.4 says check-in CREATES the swap event and
    transitions the reservation to CHECKED_IN; many implementations
    expose swap_event_id on the response either at the top level or
    via the reservation envelope. We read the check-in response, look
    for a swap_event_id field on the response (denormalized
    convenience), and if absent fall back to GET /reservations/{id}.
    """
    advance_clock_to(iso_plus(reservation["slot_start_at"], seconds=1))
    resp = api_client.check_in_reservation(
        reservation["id"],
        make_operator_headers(scene["station"]["id"]),
    )
    res_data = get_success_data(resp)
    swap_event_id = (
        res_data.get("swap_event_id")
        or (res_data.get("swap_event") or {}).get("id")
    )
    if not swap_event_id:
        # Re-fetch reservation to look for swap_event_id there.
        ref = api_client.get_reservation(
            reservation["id"],
            make_operator_headers(scene["station"]["id"]),
        )
        ref_data = get_success_data(ref)
        swap_event_id = (
            ref_data.get("swap_event_id")
            or (ref_data.get("swap_event") or {}).get("id")
        )
    assert swap_event_id, (
        "Setup failed: implementation did not expose swap_event_id "
        "via check-in response or reservation detail; PRD §3.4 says a "
        "SwapEvent is created at check-in — its id must be reachable."
    )
    se = api_client.get_swap_event(
        swap_event_id,
        make_operator_headers(scene["station"]["id"]),
    )
    return res_data, get_success_data(se)


def drive_swap_to_inspected(
    scene: Dict[str, Any], reservation: Dict[str, Any],
    *, outgoing_soc_pct: float = 30.0,
) -> Dict[str, Any]:
    """check-in → inspect. Returns the SwapEvent."""
    _, se = perform_check_in_and_fetch_swap_event(scene, reservation)
    resp = api_client.inspect_swap_event(
        se["id"], inspect_payload(outgoing_soc_pct),
        make_operator_headers(scene["station"]["id"]),
    )
    return get_success_data(resp)


def drive_swap_to_uninstalled(
    scene: Dict[str, Any], reservation: Dict[str, Any],
    *, outgoing_soc_pct: float = 30.0,
) -> Dict[str, Any]:
    """check-in → inspect → uninstall. Returns the SwapEvent."""
    se = drive_swap_to_inspected(
        scene, reservation, outgoing_soc_pct=outgoing_soc_pct,
    )
    resp = api_client.uninstall_swap_event(
        se["id"],
        make_operator_headers(scene["station"]["id"]),
    )
    return get_success_data(resp)


def drive_swap_to_installed(
    scene: Dict[str, Any], reservation: Dict[str, Any],
    *, outgoing_soc_pct: float = 30.0,
    verify: bool = True,
) -> Dict[str, Any]:
    """check-in → inspect → uninstall → install. Returns the SwapEvent."""
    se = drive_swap_to_uninstalled(
        scene, reservation, outgoing_soc_pct=outgoing_soc_pct,
    )
    resp = api_client.install_swap_event(
        se["id"], install_payload(verify=verify),
        make_operator_headers(scene["station"]["id"]),
    )
    return get_success_data(resp)


def drive_swap_to_completed(
    scene: Dict[str, Any], reservation: Dict[str, Any],
    *, outgoing_soc_pct: float = 30.0,
) -> Dict[str, Any]:
    """Full forward path: check-in → inspect → uninstall → install →
    complete. Returns the COMPLETED SwapEvent."""
    se = drive_swap_to_installed(
        scene, reservation, outgoing_soc_pct=outgoing_soc_pct,
    )
    resp = api_client.complete_swap_event(
        se["id"],
        make_operator_headers(scene["station"]["id"]),
    )
    return get_success_data(resp)


def find_billing_record_for_swap(
    scene: Dict[str, Any], swap_event_id: str,
    member_id: str,
) -> Dict[str, Any]:
    """List BillingRecord rows for the member and find the one tied to
    the completed swap event. PRD §3.7 says the billing record is
    "linked back via swap_event_id"."""
    resp = api_client.list_billing_records(
        make_member_headers(member_id),
        params={"member_id": member_id, "limit": 100},
    )
    body = resp.json()
    records = body.get("data", [])
    matches = [
        r for r in records if r.get("swap_event_id") == swap_event_id
    ]
    assert matches, (
        f"Setup failed: no BillingRecord found for swap_event_id="
        f"{swap_event_id} on member {member_id}; PRD §3.7 says complete "
        f"'creates the corresponding BillingRecord linked back via "
        f"swap_event_id'."
    )
    return matches[0]


# ---------------------------------------------------------------------------
# Tier 4: Battery-state shortcuts
# ---------------------------------------------------------------------------
def drive_battery_to_charging(scene: Dict[str, Any], battery_id: str,
                              slot_id: Optional[str] = None,
                              ) -> Dict[str, Any]:
    """Move an IDLE battery to CHARGING in a target slot."""
    slot = slot_id or scene["slots"][0]["id"]
    resp = api_client.start_charging(
        battery_id, start_charging_payload(slot),
        make_operator_headers(scene["station"]["id"]),
    )
    return get_success_data(resp)


def finish_charge(scene: Dict[str, Any], battery_id: str,
                  *, soc_pct: float = 100.0,
                  capacity_test_kwh: float = 50.0,
                  internal_resistance_mohm: float = 50.0,
                  avg_temperature_c: float = 25.0,
                  ) -> Dict[str, Any]:
    """Finish-charging with explicit SOH inputs (PRD §3.2 / §3.5)."""
    resp = api_client.finish_charging(
        battery_id,
        finish_charging_payload(
            soc_pct=soc_pct,
            capacity_test_kwh=capacity_test_kwh,
            internal_resistance_mohm=internal_resistance_mohm,
            avg_temperature_c=avg_temperature_c,
        ),
        make_operator_headers(scene["station"]["id"]),
    )
    return get_success_data(resp)


def report_battery_fault(scene: Dict[str, Any], battery_id: str,
                         *, reason: Optional[str] = None,
                         ) -> Dict[str, Any]:
    resp = api_client.report_fault(
        battery_id, report_fault_payload(reason=reason),
        make_operator_headers(scene["station"]["id"]),
    )
    return get_success_data(resp)


def retire_battery_via_recall(scene: Dict[str, Any],
                              battery: Dict[str, Any],
                              ) -> Dict[str, Any]:
    """Apply a manufacturer recall to a single IDLE/CHARGING battery.
    PRD §3.6: 'For each matching battery currently in IDLE or CHARGING,
    the platform sets recall_flag to true, transitions the battery to
    RETIRED, sets cascade_stage directly to END_OF_LIFE'."""
    resp = api_client.create_recall(
        {
            "battery_model_code": battery["battery_model_code"],
            "serial_numbers": [battery["serial_number"]],
        },
        TEST_USERS["platform_admin_headers"],
    )
    get_success_data(resp)
    refreshed = api_client.get_battery(
        battery["id"], TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(refreshed)


def set_battery_cycle_count_via_finishes(
    scene: Dict[str, Any], battery_id: str, target_count: int,
    *, slot_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive a battery's cycle_count up to `target_count` by performing
    IDLE→CHARGING→IDLE round-trips. The slot must be empty between
    iterations (finish-charging releases it per PRD §3.2). All
    finish-charging calls use SOH-neutral inputs (cap=50, res=50, t=25)
    so SOH stays at 100, grade A — no auto-retire.

    Returns the final Battery row.
    """
    slot = slot_id or scene["slots"][0]["id"]
    current = api_client.get_battery(
        battery_id, TEST_USERS["platform_admin_headers"],
    )
    bat = get_success_data(current)
    while bat["cycle_count"] < target_count:
        drive_battery_to_charging(scene, battery_id, slot_id=slot)
        bat = finish_charge(
            scene, battery_id,
            soc_pct=100.0, capacity_test_kwh=50.0,
            internal_resistance_mohm=50.0, avg_temperature_c=25.0,
        )
    return bat


# ---------------------------------------------------------------------------
# Tier 5: No-show / member-block helpers
# ---------------------------------------------------------------------------
def create_member_with_prior_no_shows(
    *, prior_no_shows: int,
    rated_capacity_kwh: float = 50.0,
) -> Dict[str, Any]:
    """Build a scene where the Member already has `prior_no_shows`
    NO_SHOW reservations within the 30-day window.

    Strategy:
      - Build a basic scene with enough IDLE batteries to soft-hold
        each of the no-show reservations independently.
      - For each prior_no_show: book a reservation, advance clock past
        its slot_end_at, run the no-show sweep, then advance the clock
        forward by 1 minute and continue.

    Returns the same dict shape as setup_basic_scene plus a key
    'prior_no_show_reservations' (the NO_SHOW reservations).
    """
    base_clock = now_iso()
    advance_clock_to(base_clock)
    scene = setup_basic_scene(
        total_slots=max(4, prior_no_shows + 1),
        num_idle_batteries=prior_no_shows + 1,
    )
    no_shows: List[Dict[str, Any]] = []
    cursor = base_clock
    for i in range(prior_no_shows):
        # Slot starts cursor + 10 min; ends cursor + 25 min.
        slot_start = iso_plus(cursor, minutes=10)
        slot_end = iso_plus(slot_start, minutes=RESERVATION_SLOT_MINUTES)
        r = reservation_at(
            scene, slot_start_iso=slot_start, slot_end_iso=slot_end,
        )
        # Advance past slot_end.
        cursor = iso_plus(slot_end, minutes=1)
        advance_clock_to(cursor)
        sweep = api_client.run_no_show_sweep(
            TEST_USERS["platform_admin_headers"],
        )
        get_success_data(sweep)
        no_shows.append(r)
    scene["prior_no_show_reservations"] = no_shows
    scene["base_clock"] = cursor
    return scene


# ---------------------------------------------------------------------------
# Tier 6: Dispatch & cross-station helpers
# ---------------------------------------------------------------------------
def setup_two_station_scene(
    *, idle_at_source: int = 1,
    rated_capacity_kwh: float = 50.0,
) -> Dict[str, Any]:
    """Two stations with shared battery model and one idle battery at the
    source. Returns dict: source, dest, battery_model, vehicle_model,
    idle_batteries."""
    src = create_station(total_slots=2, name=f"Src-{uuid.uuid4().hex[:6]}")
    dst = create_station(total_slots=2, name=f"Dst-{uuid.uuid4().hex[:6]}")
    add_charging_slot(src["id"], 1)
    add_charging_slot(src["id"], 2)
    add_charging_slot(dst["id"], 1)
    add_charging_slot(dst["id"], 2)
    bm, vm = setup_models_and_compat(
        rated_capacity_kwh=rated_capacity_kwh,
    )
    idle = []
    for _ in range(idle_at_source):
        idle.append(
            create_battery(
                station_id=src["id"], battery_model_code=bm["code"],
            )
        )
    return {
        "source": src, "dest": dst,
        "battery_model": bm, "vehicle_model": vm,
        "idle_batteries": idle,
    }


def create_dispatch(source_id: str, dest_id: str,
                    battery_id: str) -> Dict[str, Any]:
    resp = api_client.create_dispatch_order(
        create_dispatch_order_payload(
            source_station_id=source_id,
            dest_station_id=dest_id,
            battery_id=battery_id,
        ),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Tier 7: Billing shortcuts
# ---------------------------------------------------------------------------
def pay_billing(member_id: str, record_id: str) -> Dict[str, Any]:
    resp = api_client.pay_billing_record(
        record_id, make_member_headers(member_id),
    )
    return get_success_data(resp)


def refund_billing(record_id: str, *, refund_cents: int) -> Dict[str, Any]:
    resp = api_client.refund_billing_record(
        record_id, refund_payload(refund_cents),
        TEST_USERS["platform_admin_headers"],
    )
    return get_success_data(resp)


__all__ = [
    "now_iso",
    "iso_plus",
    "advance_clock_to",
    "create_station",
    "add_charging_slot",
    "create_battery_model",
    "create_vehicle_model",
    "create_compatibility",
    "create_battery",
    "create_member",
    "create_vehicle",
    "setup_models_and_compat",
    "setup_basic_scene",
    "book_reservation",
    "reservation_at",
    "check_in",
    "perform_check_in_and_fetch_swap_event",
    "drive_swap_to_inspected",
    "drive_swap_to_uninstalled",
    "drive_swap_to_installed",
    "drive_swap_to_completed",
    "find_billing_record_for_swap",
    "drive_battery_to_charging",
    "finish_charge",
    "report_battery_fault",
    "retire_battery_via_recall",
    "set_battery_cycle_count_via_finishes",
    "create_member_with_prior_no_shows",
    "setup_two_station_scene",
    "create_dispatch",
    "pay_billing",
    "refund_billing",
]
