"""Room creation, maintenance windows, and the room-time-geometry overlap rules."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    add_minutes,
    assert_maintenance_window,
    assert_room,
    create_maintenance_window_payload,
    create_room,
    create_room_payload,
    create_session_slot_payload,
    create_session_slot,
    make_venue_operator_headers,
    setup_basic_scenario,
    validate_error,
    validate_success,
)


# ─── Room basics ──────────────────────────────────────────────────────────

def test_create_room_default_turnover_minutes(api):
    """PRD §3.1: "A `turnover_minutes` field, defaulting to 30 and bounded between 0 and 240 inclusive."

    Claim: omitting turnover_minutes yields the documented default of 30.
    """
    venue, _, _ = setup_basic_scenario()
    headers = make_venue_operator_headers(venue["id"])
    payload = {"name": "room-default", "capacity_min": 2, "capacity_max": 6}
    room = validate_success(api.create_room(venue["id"], payload, headers), expected_status=201)
    assert_room(room)
    assert room["turnover_minutes"] == 30


def test_create_room_capacity_min_at_least_one(api):
    """PRD §3.1: "The `capacity_min` is the minimum number of simultaneous players the room supports and must be at least 1."

    Claim: capacity_min=0 is rejected with ERR_INVALID_REQUEST.
    """
    venue, _, _ = setup_basic_scenario()
    headers = make_venue_operator_headers(venue["id"])
    payload = create_room_payload(capacity_min=0, capacity_max=4)
    resp = api.create_room(venue["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_room_capacity_max_above_20_rejected(api):
    """PRD §3.1: "`capacity_max` must be at least `capacity_min` and at most 20."

    Claim: capacity_max=21 is rejected with ERR_INVALID_REQUEST.
    """
    venue, _, _ = setup_basic_scenario()
    headers = make_venue_operator_headers(venue["id"])
    payload = create_room_payload(capacity_min=2, capacity_max=21)
    resp = api.create_room(venue["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


# ─── Maintenance window basics ────────────────────────────────────────────

def test_create_maintenance_window_starts_before_ends(api):
    """PRD §3.1: "A `VenueOperator` schedules a window with `starts_at` and `ends_at` (the latter strictly greater than the former)."

    Claim: ends_at <= starts_at yields ERR_INVALID_REQUEST.
    """
    venue, room, _ = setup_basic_scenario()
    headers = make_venue_operator_headers(venue["id"])
    starts = "2030-06-01T10:00:00.000Z"
    payload = create_maintenance_window_payload(starts, starts)  # equal -> invalid
    resp = api.create_maintenance_window(venue["id"], room["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_create_maintenance_window_ok(api):
    """PRD §3.1: "A `VenueOperator` schedules a window with `starts_at` and `ends_at` ... and a server-defaulted `status` of `SCHEDULED`."

    Claim: a valid maintenance window is created in SCHEDULED.
    """
    venue, room, _ = setup_basic_scenario()
    headers = make_venue_operator_headers(venue["id"])
    payload = create_maintenance_window_payload("2030-06-01T10:00:00.000Z", "2030-06-01T11:00:00.000Z", reason="reset")
    mw = validate_success(api.create_maintenance_window(venue["id"], room["id"], payload, headers), expected_status=201)
    assert_maintenance_window(mw)
    assert mw["status"] == "SCHEDULED"


# ─── §3.4 Room time geometry — slot overlap ──────────────────────────────

def test_slot_overlap_with_turnover_extended_interval_rejected(api):
    """PRD §3.4: "the system computes `P`'s start as `P.starts_at` and `P`'s effective finish as `P.ends_at` plus the room's `turnover_minutes` — the turnover gap acts as a forward-extending exclusive guard that no following item may intrude upon."
    PRD §3.4: "A conflict on slot creation is rejected with `ERR_SLOT_OVERLAP_CONFLICT`."

    Claim: an existing slot's [starts_at, ends_at + turnover) blocks a new slot starting inside that extended interval.
    Setup: room turnover=30; existing slot [T0, T0+90m) (theme.duration=90); proposed slot starts at T0+90m (inside the 30-minute turnover guard).
    """
    venue, room, theme = setup_basic_scenario(
        room_overrides={"turnover_minutes": 30, "capacity_min": 2, "capacity_max": 4},
        theme_overrides={"duration_minutes": 90},
    )
    headers = make_venue_operator_headers(venue["id"])
    base = "2030-06-01T10:00:00.000Z"
    s1 = create_session_slot(venue, room, theme, starts_at=base, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    # Proposed slot starts at base + 90m (== existing.ends_at) — inside turnover guard (30m).
    proposed_start = add_minutes(base, 90)
    payload = create_session_slot_payload(theme["id"], proposed_start, "PRIVATE_ONLY", theme["min_players"])
    resp = api.create_session_slot(venue["id"], room["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_SLOT_OVERLAP_CONFLICT.value)


def test_slot_back_to_back_at_turnover_boundary_succeeds(api):
    """PRD §3.4: "two intervals that share an endpoint do not collide" (PRD §2.6 closed-open) and §3.4: "the turnover gap acts as a forward-extending exclusive guard."

    Claim: a new slot starting exactly at existing.ends_at + turnover_minutes does NOT overlap.
    """
    venue, room, theme = setup_basic_scenario(
        room_overrides={"turnover_minutes": 30, "capacity_min": 2, "capacity_max": 4},
        theme_overrides={"duration_minutes": 90},
    )
    base = "2030-06-01T10:00:00.000Z"
    create_session_slot(venue, room, theme, starts_at=base, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    # Effective finish of existing = 90m + 30m turnover = 120m after base.
    proposed_start = add_minutes(base, 120)
    new_slot = create_session_slot(venue, room, theme, starts_at=proposed_start, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    assert new_slot["schedule_status"] == "SCHEDULED"


def test_maintenance_overlap_with_slot_turnover_guard(api):
    """PRD §3.4: "For an existing slot `X`, its effective finish is likewise `X.ends_at` plus `R.turnover_minutes`. For an existing maintenance window, its effective finish is its own `ends_at` — the turnover guard is **not** applied to maintenance windows."
    PRD §3.4: "a conflict on maintenance creation is rejected with `ERR_MAINTENANCE_OVERLAP_CONFLICT`."

    Claim: a maintenance window proposed inside an existing slot's turnover guard yields ERR_MAINTENANCE_OVERLAP_CONFLICT.
    """
    venue, room, theme = setup_basic_scenario(
        room_overrides={"turnover_minutes": 30, "capacity_min": 2, "capacity_max": 4},
        theme_overrides={"duration_minutes": 90},
    )
    headers = make_venue_operator_headers(venue["id"])
    base = "2030-06-01T10:00:00.000Z"
    create_session_slot(venue, room, theme, starts_at=base, visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    # Slot's effective finish = base+120m. Maintenance starting at base+90m, ending at base+100m intrudes.
    payload = create_maintenance_window_payload(add_minutes(base, 90), add_minutes(base, 100))
    resp = api.create_maintenance_window(venue["id"], room["id"], payload, headers)
    validate_error(resp, ApiErrorId.ERR_MAINTENANCE_OVERLAP_CONFLICT.value)


def test_slot_overlap_back_to_back_with_maintenance_one_sided_guard(api):
    """PRD §3.4: "the slot-versus-maintenance case extends [the turnover guard] on the slot side only."

    Claim: a NEW slot starting exactly at an existing maintenance window's ends_at does NOT overlap (maintenance has no forward turnover guard).
    """
    venue, room, theme = setup_basic_scenario(
        room_overrides={"turnover_minutes": 30, "capacity_min": 2, "capacity_max": 4},
        theme_overrides={"duration_minutes": 90},
    )
    headers = make_venue_operator_headers(venue["id"])
    base = "2030-06-01T10:00:00.000Z"
    payload = create_maintenance_window_payload(base, add_minutes(base, 60))
    validate_success(api.create_maintenance_window(venue["id"], room["id"], payload, headers), expected_status=201)
    # Slot starting at base+60 (== maintenance.ends_at) — closed-open intervals don't collide.
    slot = create_session_slot(venue, room, theme, starts_at=add_minutes(base, 60), visibility="PRIVATE_ONLY", required_seats_for_launch=theme["min_players"])
    assert slot["schedule_status"] == "SCHEDULED"
