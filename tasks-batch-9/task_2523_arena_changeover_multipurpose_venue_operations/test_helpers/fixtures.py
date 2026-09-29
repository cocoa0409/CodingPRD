"""Composite setup helpers.

Every helper builds its preconditions from scratch through PRD-declared
endpoints only, because each test starts against an empty database.  Setup
calls use the lenient ``get_success_data`` validator so that a broken
precondition surfaces as a setup failure rather than as a confusing
assertion failure inside a test.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    CLOCK_STARTUP_UTC,
    DIRECTOR_USER_ID,
    PROFILE_CONCERT,
    PROFILE_COURT,
    PROFILE_FAMILY,
    PROFILE_ICE,
    SUPERVISOR_USER_ID,
    VENUE_DEFAULTS,
)
from .test_users import (
    TEST_USERS,
    make_anchor_tenant_rep_headers,
    make_changeover_supervisor_headers,
    make_director_headers,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["booking_manager_headers"]
SUPERVISOR = TEST_USERS["changeover_supervisor_headers"]
COORDINATOR = TEST_USERS["labor_coordinator_headers"]

PROFILE_LIBRARY = {
    "ICE": PROFILE_ICE,
    "CONCERT": PROFILE_CONCERT,
    "COURT": PROFILE_COURT,
    "FAMILY": PROFILE_FAMILY,
}


# ==========================================================================
# Tier 0 — single-call primitives
# ==========================================================================
def set_clock(to_iso8601: str, headers: dict = None) -> dict:
    """Move the logical clock.  Only a VenueOperationsDirector may do this."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or DIRECTOR)
    )


def register_venue(headers: dict = None, **overrides) -> dict:
    payload = dict(VENUE_DEFAULTS)
    payload.update(overrides)
    return get_success_data(api_client.create_venue(payload, headers or DIRECTOR))


def declare_profile(venue_id: str, template: str, headers: dict = None, **overrides) -> dict:
    payload = dict(PROFILE_LIBRARY[template])
    payload.update(overrides)
    return get_success_data(
        api_client.create_configuration_profile(venue_id, payload, headers or DIRECTOR)
    )


def register_tenant(
    venue_id: str,
    name: str = "Lakeside Hockey Club",
    hold_priority_tier: str = "TIER_2",
    guaranteed_holds_per_season: int = 5,
    headers: dict = None,
) -> dict:
    payload = {
        "name": name,
        "hold_priority_tier": hold_priority_tier,
        "guaranteed_holds_per_season": guaranteed_holds_per_season,
    }
    return get_success_data(
        api_client.create_anchor_tenant(venue_id, payload, headers or DIRECTOR)
    )


def create_equipment_pool(
    venue_id: str,
    asset_class: str = "FLOOR_PANEL_SET",
    units_total: int = 10,
    service_interval_cycles: int = 12,
    headers: dict = None,
) -> dict:
    payload = {
        "asset_class": asset_class,
        "units_total": units_total,
        "service_interval_cycles": service_interval_cycles,
    }
    return get_success_data(
        api_client.create_equipment_asset(venue_id, payload, headers or DIRECTOR)
    )


def draft_booking(
    venue_id: str,
    config_profile_id: str,
    title: str,
    event_start_utc: str,
    event_end_utc: str,
    expected_attendance: int = 8_000,
    rigging_load_kg: float = 0,
    tenant_id: str = None,
    promoter_name: str = None,
    headers: dict = None,
) -> dict:
    payload = {
        "venue_id": venue_id,
        "config_profile_id": config_profile_id,
        "title": title,
        "event_start_utc": event_start_utc,
        "event_end_utc": event_end_utc,
        "expected_attendance": expected_attendance,
        "rigging_load_kg": rigging_load_kg,
    }
    if tenant_id is not None:
        payload["tenant_id"] = tenant_id
    else:
        payload["promoter_name"] = promoter_name or "Northline Live"
    return get_success_data(
        api_client.create_event_booking(payload, headers or MANAGER)
    )


def place_hold(booking_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.hold_event_booking(booking_id, headers or MANAGER)
    )


def read_venue(venue_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_venue(venue_id, headers or MANAGER))


def venue_version(venue_id: str, headers: dict = None) -> int:
    return read_venue(venue_id, headers)["version"]


def confirm_booking(booking_id: str, venue_id: str, headers: dict = None) -> dict:
    """Confirm a held booking against the arena's currently observed version."""
    payload = {"expected_venue_version": venue_version(venue_id, headers)}
    return get_success_data(
        api_client.confirm_event_booking(booking_id, payload, headers or MANAGER)
    )


def release_booking(booking_id: str, reason: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.release_event_booking(
            booking_id, {"reason": reason}, headers or MANAGER
        )
    )


def install_ice_sheet(
    venue_id: str,
    config_profile_id: str,
    dehumidification_lph_applied: float = 120,
    sheet_thickness_mm: float = 32,
    headers: dict = None,
) -> dict:
    payload = {
        "config_profile_id": config_profile_id,
        "dehumidification_lph_applied": dehumidification_lph_applied,
        "sheet_thickness_mm": sheet_thickness_mm,
    }
    return get_success_data(
        api_client.create_ice_sheet(venue_id, payload, headers or SUPERVISOR)
    )


def transition_ice_sheet(
    sheet_id: str, to_status: str, dehumidification_lph_applied: float = None,
    headers: dict = None,
) -> dict:
    payload = {"to_status": to_status}
    if dehumidification_lph_applied is not None:
        payload["dehumidification_lph_applied"] = dehumidification_lph_applied
    return get_success_data(
        api_client.transition_ice_sheet(sheet_id, payload, headers or SUPERVISOR)
    )


def open_changeover_order(
    venue_id: str,
    from_booking_id: str,
    to_booking_id: str,
    crew_headcount: int = 40,
    headers: dict = None,
) -> dict:
    payload = {
        "from_booking_id": from_booking_id,
        "to_booking_id": to_booking_id,
        "crew_headcount": crew_headcount,
        "expected_venue_version": venue_version(venue_id),
    }
    return get_success_data(
        api_client.create_changeover_order(payload, headers or SUPERVISOR)
    )


def progress_order(order_id: str, dimension: str, to_stage: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.progress_changeover_order(
            order_id, {"dimension": dimension, "to_stage": to_stage},
            headers or SUPERVISOR,
        )
    )


def rework_order(order_id: str, dimension: str, reason: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.rework_changeover_order(
            order_id, {"dimension": dimension, "reason": reason}, headers or SUPERVISOR
        )
    )


def issue_equipment(
    asset_id: str, changeover_order_id: str, units_issued: int, headers: dict = None
) -> dict:
    payload = {
        "asset_id": asset_id,
        "changeover_order_id": changeover_order_id,
        "units_issued": units_issued,
    }
    return get_success_data(
        api_client.create_equipment_issue(payload, headers or SUPERVISOR)
    )


def return_equipment(issue_id: str, damaged_units: int = 0, headers: dict = None) -> dict:
    return get_success_data(
        api_client.return_equipment_issue(
            issue_id, headers or SUPERVISOR, {"damaged_units": damaged_units}
        )
    )


def maintenance(asset_id: str, action: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.equipment_asset_maintenance(
            asset_id, {"action": action}, headers or DIRECTOR
        )
    )


def create_labor_call(
    craft: str,
    headcount: int,
    call_start_utc: str,
    call_end_utc: str,
    guaranteed_hours: float = 4,
    changeover_order_id: str = None,
    booking_id: str = None,
    headers: dict = None,
) -> dict:
    payload = {
        "craft": craft,
        "headcount": headcount,
        "call_start_utc": call_start_utc,
        "call_end_utc": call_end_utc,
        "guaranteed_hours": guaranteed_hours,
    }
    if changeover_order_id is not None:
        payload["changeover_order_id"] = changeover_order_id
    if booking_id is not None:
        payload["booking_id"] = booking_id
    return get_success_data(
        api_client.create_labor_call(payload, headers or COORDINATOR)
    )


def reserve_dock(
    booking_id: str,
    dock_number: int,
    purpose: str,
    window_start_utc: str,
    window_end_utc: str,
    truck_count: int = 6,
    headers: dict = None,
) -> dict:
    payload = {
        "dock_number": dock_number,
        "purpose": purpose,
        "window_start_utc": window_start_utc,
        "window_end_utc": window_end_utc,
        "truck_count": truck_count,
    }
    return get_success_data(
        api_client.create_dock_slot_reservation(
            booking_id, payload, headers or SUPERVISOR
        )
    )


def open_challenge(
    booking_id: str,
    challenger_tenant_id: str,
    challenger_booking_id: str,
    headers: dict = None,
) -> dict:
    payload = {
        "booking_id": booking_id,
        "challenger_tenant_id": challenger_tenant_id,
        "challenger_booking_id": challenger_booking_id,
    }
    return get_success_data(
        api_client.create_hold_challenge(
            payload, headers or make_anchor_tenant_rep_headers(challenger_tenant_id)
        )
    )


def rule_challenge(
    challenge_id: str, decision: str, ruling_note: str = None, headers: dict = None
) -> dict:
    payload = {"decision": decision}
    if ruling_note is not None:
        payload["ruling_note"] = ruling_note
    return get_success_data(
        api_client.rule_hold_challenge(challenge_id, payload, headers or MANAGER)
    )


def withdraw_challenge(challenge_id: str, challenger_tenant_id: str) -> dict:
    return get_success_data(
        api_client.withdraw_hold_challenge(
            challenge_id, make_anchor_tenant_rep_headers(challenger_tenant_id)
        )
    )


# ==========================================================================
# Tier 1 — arena standing-up
# ==========================================================================
CANONICAL_ICE_EVENT = ("2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z")
CANONICAL_CONCERT_EVENT = ("2026-09-10T16:00:00Z", "2026-09-10T19:00:00Z")

FULL_PROGRESSION = [
    ("FLOOR", "STRIKING"),
    ("FLOOR", "LAYING"),
    ("FLOOR", "FLOOR_COMPLETE"),
    ("SEATING", "RETRACTING"),
    ("SEATING", "CURTAINING"),
    ("SEATING", "SEATING_COMPLETE"),
    ("INFRA", "UTILITY_SET"),
    ("INFRA", "NETWORK_SET"),
    ("INFRA", "BROADCAST_READY"),
]


def setup_arena(profiles=("ICE", "CONCERT"), clock: str = CLOCK_STARTUP_UTC, **venue_overrides) -> dict:
    """Register one arena and declare the named house configurations.

    Returns ``{"venue": ..., "venue_id": ..., "profiles": {"ICE": ..., ...}}``.
    """
    if clock:
        set_clock(clock)
    venue = register_venue(**venue_overrides)
    result = {"venue": venue, "venue_id": venue["id"], "profiles": {}}
    for template in profiles:
        result["profiles"][template] = declare_profile(venue["id"], template)
    return result


def setup_arena_with_ice_sheet(
    dehumidification_lph_applied: float = 120,
    sheet_thickness_mm: float = 32,
    to_status: str = "IN_SERVICE",
    clock: str = CLOCK_STARTUP_UTC,
    profiles=("ICE", "CONCERT"),
    **venue_overrides,
) -> dict:
    """Arena plus a flooded ice sheet driven to ``to_status`` (or left BUILDING)."""
    arena = setup_arena(profiles=profiles, clock=clock, **venue_overrides)
    sheet = install_ice_sheet(
        arena["venue_id"],
        arena["profiles"]["ICE"]["id"],
        dehumidification_lph_applied=dehumidification_lph_applied,
        sheet_thickness_mm=sheet_thickness_mm,
    )
    if to_status and to_status != "BUILDING":
        sheet = transition_ice_sheet(sheet["id"], "IN_SERVICE")
        if to_status != "IN_SERVICE":
            sheet = transition_ice_sheet(sheet["id"], to_status)
    arena["ice_sheet"] = sheet
    return arena


# ==========================================================================
# Tier 2 — booking pairs and turnarounds
# ==========================================================================
def setup_ice_to_concert_bookings(
    arena: dict,
    ice_event=CANONICAL_ICE_EVENT,
    concert_event=CANONICAL_CONCERT_EVENT,
    ice_rigging_kg: float = 3_000,
    concert_rigging_kg: float = 5_000,
    confirm_incoming: bool = False,
) -> dict:
    """An outgoing ice show and an incoming concert, both HELD on the arena.

    The plan for a 40-head crew between these two configurations is 708 minutes
    against a 735-minute window.
    """
    venue_id = arena["venue_id"]
    from_booking = draft_booking(
        venue_id,
        arena["profiles"]["ICE"]["id"],
        "Hockey Sep 10",
        ice_event[0],
        ice_event[1],
        expected_attendance=15_000,
        rigging_load_kg=ice_rigging_kg,
        promoter_name="Lakeside Hockey Club",
    )
    place_hold(from_booking["id"])
    to_booking = draft_booking(
        venue_id,
        arena["profiles"]["CONCERT"]["id"],
        "Concert Sep 10",
        concert_event[0],
        concert_event[1],
        expected_attendance=8_000,
        rigging_load_kg=concert_rigging_kg,
        promoter_name="Northline Live",
    )
    place_hold(to_booking["id"])
    if confirm_incoming:
        to_booking = confirm_booking(to_booking["id"], venue_id)
    arena["from_booking"] = from_booking
    arena["to_booking"] = to_booking
    return arena


def setup_ice_to_concert_turnaround(
    crew_headcount: int = 40,
    confirm_incoming: bool = False,
    clock: str = CLOCK_STARTUP_UTC,
    supervisor_headers: dict = None,
    floor_panel_units_total: int = None,
    ice_event=CANONICAL_ICE_EVENT,
    concert_event=CANONICAL_CONCERT_EVENT,
    **venue_overrides,
) -> dict:
    """Arena + ICE and CONCERT profiles + held bookings + one open turnaround.

    Returns the arena dict extended with ``from_booking``, ``to_booking``,
    ``order`` and, when a pool size is requested, ``floor_pool``.
    """
    arena = setup_arena(profiles=("ICE", "CONCERT"), clock=clock, **venue_overrides)
    if floor_panel_units_total is not None:
        arena["floor_pool"] = create_equipment_pool(
            arena["venue_id"], "FLOOR_PANEL_SET", floor_panel_units_total
        )
    setup_ice_to_concert_bookings(
        arena,
        ice_event=ice_event,
        concert_event=concert_event,
        confirm_incoming=confirm_incoming,
    )
    arena["order"] = open_changeover_order(
        arena["venue_id"],
        arena["from_booking"]["id"],
        arena["to_booking"]["id"],
        crew_headcount=crew_headcount,
        headers=supervisor_headers,
    )
    return arena


def drive_order_to_ready_for_signoff(
    order_id: str,
    start_clock: str = None,
    complete_clock: str = None,
    headers: dict = None,
) -> dict:
    """Advance all three dimensions to their terminal stages.

    ``start_clock`` is applied before the first progress call, which is what
    stamps ``started_at_utc``; ``complete_clock`` is applied immediately before
    the last progress call, which is what stamps ``completed_at_utc``.
    """
    if start_clock:
        set_clock(start_clock)
    for dimension, stage in FULL_PROGRESSION[:-1]:
        progress_order(order_id, dimension, stage, headers=headers)
    if complete_clock:
        set_clock(complete_clock)
    last_dimension, last_stage = FULL_PROGRESSION[-1]
    return progress_order(order_id, last_dimension, last_stage, headers=headers)


def setup_covering_turnaround_ready_for_signoff(
    crew_headcount: int = 40,
    start_clock: str = "2026-09-10T04:00:00Z",
    complete_clock: str = "2026-09-10T16:30:00Z",
    floor_panel_units_total: int = 10,
    floor_panel_units_issued: int = 3,
    supervisor_headers: dict = None,
    ice_sheet: bool = False,
    ice_sheet_kwargs: dict = None,
    **venue_overrides,
) -> dict:
    """A covering ice-to-concert turnaround sitting in READY_FOR_SIGNOFF.

    The incoming concert is CONFIRMED first because no progress may be recorded
    against a merely held incoming show.  Three floor-panel sets are issued so
    that the floor dimension clears its protection gate.
    """
    arena = setup_arena(profiles=("ICE", "CONCERT"), **venue_overrides)
    if ice_sheet:
        kwargs = dict(ice_sheet_kwargs or {})
        sheet = install_ice_sheet(
            arena["venue_id"], arena["profiles"]["ICE"]["id"], **kwargs
        )
        arena["ice_sheet"] = transition_ice_sheet(sheet["id"], "IN_SERVICE")
    arena["floor_pool"] = create_equipment_pool(
        arena["venue_id"], "FLOOR_PANEL_SET", floor_panel_units_total
    )
    setup_ice_to_concert_bookings(arena, confirm_incoming=True)
    arena["order"] = open_changeover_order(
        arena["venue_id"],
        arena["from_booking"]["id"],
        arena["to_booking"]["id"],
        crew_headcount=crew_headcount,
        headers=supervisor_headers,
    )
    arena["floor_issue"] = issue_equipment(
        arena["floor_pool"]["id"], arena["order"]["id"], floor_panel_units_issued,
        headers=supervisor_headers,
    )
    arena["order"] = drive_order_to_ready_for_signoff(
        arena["order"]["id"],
        start_clock=start_clock,
        complete_clock=complete_clock,
        headers=supervisor_headers,
    )
    return arena


# ==========================================================================
# Tier 3 — anchor tenants, holds and challenges
# ==========================================================================
def setup_two_tenants_with_incumbent_hold(
    incumbent_tier: str = "TIER_2",
    challenger_tier: str = "TIER_1",
    incumbent_holds: int = 5,
    challenger_holds: int = 5,
    clock: str = CLOCK_STARTUP_UTC,
    incumbent_event=("2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z"),
    challenger_event=("2026-09-10T00:00:00Z", "2026-09-10T03:00:00Z"),
    **venue_overrides,
) -> dict:
    """An incumbent tenant holding a date plus a rival tenant with a draft.

    Returns the arena dict extended with ``incumbent_tenant``,
    ``challenger_tenant``, ``incumbent_booking`` (HELD) and
    ``challenger_booking`` (DRAFT).
    """
    arena = setup_arena(profiles=("ICE",), clock=clock, **venue_overrides)
    venue_id = arena["venue_id"]
    arena["incumbent_tenant"] = register_tenant(
        venue_id, "Lakeside Hockey Club", incumbent_tier, incumbent_holds
    )
    arena["challenger_tenant"] = register_tenant(
        venue_id, "Riverton Athletics", challenger_tier, challenger_holds
    )
    incumbent = draft_booking(
        venue_id,
        arena["profiles"]["ICE"]["id"],
        "Incumbent hold",
        incumbent_event[0],
        incumbent_event[1],
        expected_attendance=15_000,
        rigging_load_kg=3_000,
        tenant_id=arena["incumbent_tenant"]["id"],
    )
    arena["incumbent_booking"] = place_hold(incumbent["id"])
    arena["challenger_booking"] = draft_booking(
        venue_id,
        arena["profiles"]["ICE"]["id"],
        "Challenger draft",
        challenger_event[0],
        challenger_event[1],
        expected_attendance=14_000,
        rigging_load_kg=2_000,
        tenant_id=arena["challenger_tenant"]["id"],
    )
    return arena


def setup_open_challenge(
    incumbent_tier: str = "TIER_2",
    challenger_tier: str = "TIER_1",
    clock: str = CLOCK_STARTUP_UTC,
    **kwargs,
) -> dict:
    """Everything ``setup_two_tenants_with_incumbent_hold`` builds, plus one OPEN challenge."""
    arena = setup_two_tenants_with_incumbent_hold(
        incumbent_tier=incumbent_tier,
        challenger_tier=challenger_tier,
        clock=clock,
        **kwargs,
    )
    arena["challenge"] = open_challenge(
        arena["incumbent_booking"]["id"],
        arena["challenger_tenant"]["id"],
        arena["challenger_booking"]["id"],
    )
    return arena


# ==========================================================================
# Tier 4 — accumulation and threshold targeting
# ==========================================================================
def accumulate_changeover_debt(target_minutes: int) -> dict:
    """Sign off one turnaround that overruns its window by ``target_minutes``.

    The canonical ice-to-concert window runs 2026-09-10T03:45Z..16:00Z, i.e.
    735 minutes.  Starting the work at 04:00Z and completing it
    ``735 + target_minutes`` minutes later produces exactly that overrun, which
    sign-off then adds to the arena's debt ledger.
    """
    from datetime import datetime, timedelta, timezone

    started = datetime(2026, 9, 10, 4, 0, tzinfo=timezone.utc)
    completed = started + timedelta(minutes=735 + target_minutes)
    arena = setup_covering_turnaround_ready_for_signoff(
        start_clock="2026-09-10T04:00:00Z",
        complete_clock=completed.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    arena["signed_order"] = get_success_data(
        api_client.signoff_changeover_order(
            arena["order"]["id"], make_director_headers("dir-signer")
        )
    )
    return arena


def sweep_holds(venue_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.hold_expiry_sweep(venue_id, headers or MANAGER))


def signoff_order(order_id: str, director_user_id: str = "dir-signer") -> dict:
    return get_success_data(
        api_client.signoff_changeover_order(
            order_id, make_director_headers(director_user_id)
        )
    )


# ==========================================================================
# Read-back helpers
# ==========================================================================
def read_booking(booking_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_event_booking(booking_id, headers or MANAGER))


def read_order(order_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_changeover_order(order_id, headers or SUPERVISOR)
    )


def read_asset(asset_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_equipment_asset(asset_id, headers or SUPERVISOR)
    )


def read_issue(issue_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_equipment_issue(issue_id, headers or SUPERVISOR)
    )


def read_challenge(challenge_id: str, headers: dict = None) -> dict:
    return get_success_data(
        api_client.get_hold_challenge(challenge_id, headers or MANAGER)
    )


def read_labor_call(call_id: str, headers: dict = None) -> dict:
    return get_success_data(api_client.get_labor_call(call_id, headers or COORDINATOR))


def read_tenant(venue_id: str, tenant_id: str, headers: dict = None) -> dict:
    """Anchor tenants have no single-row GET; read the venue-scoped listing."""
    rows, _meta = validate_paginated(
        api_client.list_anchor_tenants(
            venue_id, headers or MANAGER, {"limit": 100}
        )
    )
    matches = [row for row in rows if row["id"] == tenant_id]
    assert matches, f"tenant {tenant_id} absent from the anchor-tenant listing"
    return matches[0]


def read_ice_sheet(venue_id: str, sheet_id: str, headers: dict = None) -> dict:
    """Ice sheets have no single-row GET; read the venue-scoped listing."""
    rows, _meta = validate_paginated(
        api_client.list_ice_sheets(venue_id, headers or SUPERVISOR, {"limit": 100})
    )
    matches = [row for row in rows if row["id"] == sheet_id]
    assert matches, f"ice sheet {sheet_id} absent from the ice-sheet listing"
    return matches[0]


def read_reservation(booking_id: str, reservation_id: str, headers: dict = None) -> dict:
    """Dock slot reservations have no single-row GET; read the booking listing."""
    rows, _meta = validate_paginated(
        api_client.list_dock_slot_reservations(
            booking_id, headers or SUPERVISOR, {"limit": 100}
        )
    )
    matches = [row for row in rows if row["id"] == reservation_id]
    assert matches, f"reservation {reservation_id} absent from the booking listing"
    return matches[0]
