"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) so setup failures produce clear
"Setup failed" errors rather than confusing downstream assertion failures.

Every fixture builds its preconditions from scratch — the harness restarts the
server (empty database) before each test.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_arena_payload,
    set_clock_payload,
    create_field_payload,
    create_party_package_payload,
    create_booking_payload,
    create_waiver_profile_payload,
    create_equipment_unit_payload,
    create_rental_payload,
    create_add_on_order_payload,
    create_referee_payload,
    create_referee_assignment_payload,
    create_league_payload,
    create_league_match_payload,
)
from .test_users import TEST_USERS
from .constants import CLOCK_BASE

AM = TEST_USERS["arena_manager_headers"]
FD = TEST_USERS["front_desk_headers"]
FM = TEST_USERS["field_marshal_headers"]
LD = TEST_USERS["league_director_headers"]


# ─── Tier 1: Base provisioning (arena + clock + field) ──────────────────────
def create_arena(clock=CLOCK_BASE, **overrides):
    """Create an arena and set its clock. Returns the arena (after clock set)."""
    arena = get_success_data(api_client.create_arena(create_arena_payload(**overrides), AM))
    if clock is not None:
        arena = get_success_data(
            api_client.set_clock(set_clock_payload(arena["id"], clock), AM)
        )
    return arena


def create_field(arena_id, **overrides):
    """Create a field under an arena. Returns the field."""
    return get_success_data(
        api_client.create_field(create_field_payload(arena_id, **overrides), AM)
    )


def setup_arena_and_field(clock=CLOCK_BASE, arena_overrides=None, field_overrides=None):
    """Arena (clock set) + one field. Returns (arena, field)."""
    arena = create_arena(clock=clock, **(arena_overrides or {}))
    field = create_field(arena["id"], **(field_overrides or {}))
    return arena, field


def create_equipment(arena_id, **overrides):
    """Provision one equipment unit. Returns the unit."""
    return get_success_data(
        api_client.create_equipment_unit(create_equipment_unit_payload(arena_id, **overrides), AM)
    )


def create_referee(arena_id, **overrides):
    """Register a referee. Returns the referee."""
    return get_success_data(
        api_client.create_referee(create_referee_payload(arena_id, **overrides), AM)
    )


def create_package(arena_id, **overrides):
    """Create a party package. Returns the package."""
    return get_success_data(
        api_client.create_party_package(create_party_package_payload(arena_id, **overrides), AM)
    )


# ─── Tier 2: Bookings in lifecycle states ───────────────────────────────────
def create_held_booking(arena_id, field_id, **overrides):
    """Create a HELD booking. Returns the booking."""
    return get_success_data(
        api_client.create_booking(create_booking_payload(arena_id, field_id, **overrides), FD)
    )


def create_confirmed_booking(arena, field, **booking_overrides):
    """Create a HELD booking then confirm it (OCC version pulled live from field).
    Returns the confirmed booking."""
    booking = create_held_booking(arena["id"], field["id"], **booking_overrides)
    live_field = get_success_data(api_client.get_field(field["id"], AM))
    confirmed = get_success_data(
        api_client.confirm_booking(
            booking["id"], {"expected_field_version": live_field["version"]}, FD
        )
    )
    return confirmed


def setup_confirmed_booking(clock=CLOCK_BASE, arena_overrides=None, field_overrides=None,
                            booking_overrides=None):
    """Arena + field + a CONFIRMED booking. Returns (arena, field, booking)."""
    arena, field = setup_arena_and_field(clock, arena_overrides, field_overrides)
    booking = create_confirmed_booking(arena, field, **(booking_overrides or {}))
    return arena, field, booking


def assign_referee(arena_id, booking_id, referee_id):
    """Assign a referee to a booking. Returns the assignment."""
    return get_success_data(
        api_client.create_referee_assignment(
            create_referee_assignment_payload(arena_id, booking_id, referee_id), FM
        )
    )


def check_in_booking(booking_id, checked_in_count):
    """Check in a CONFIRMED booking. Returns the checked-in booking."""
    return get_success_data(
        api_client.check_in_booking(booking_id, {"checked_in_count": checked_in_count}, FM)
    )


def setup_checked_in_booking(clock=CLOCK_BASE, party_size=4, field_overrides=None,
                             arena_overrides=None, booking_overrides=None,
                             with_referee=False, referee_certified=True):
    """Arena + field + CONFIRMED booking driven to CHECKED_IN.

    If with_referee, registers and assigns a (certified by default) referee before
    check-in so the referee gate is satisfied. Returns
    (arena, field, booking, referee_or_None).
    """
    bo = dict(booking_overrides or {})
    bo.setdefault("party_size", party_size)
    arena, field, booking = setup_confirmed_booking(
        clock=clock, arena_overrides=arena_overrides, field_overrides=field_overrides,
        booking_overrides=bo,
    )
    referee = None
    if with_referee:
        referee = create_referee(arena["id"], certified_paintball=referee_certified)
        assign_referee(arena["id"], booking["id"], referee["id"])
    checked_in = check_in_booking(booking["id"], min(party_size, booking["party_size"]))
    return arena, field, checked_in, referee


# ─── Tier 3: Equipment rental lifecycle ─────────────────────────────────────
def reserve_rental(arena_id, booking_id, equipment_unit_id):
    """Reserve an equipment unit for a booking (HELD rental). Returns the rental."""
    return get_success_data(
        api_client.create_rental(
            create_rental_payload(arena_id, booking_id, equipment_unit_id), FD
        )
    )


def setup_checked_out_rental(deposit_cents=5000, unit_type="MARKER",
                             game_mode="PAINTBALL", party_size=6, clock=CLOCK_BASE,
                             condition_grade="A"):
    """Full chain to a CHECKED_OUT rental:
    arena + field + equipment + (referee if paintball) + CONFIRMED booking +
    HELD rental + check-in (rental -> CHECKED_OUT).

    Returns (arena, field, unit, booking, rental).
    """
    arena = create_arena(clock=clock, marker_pool_total=1 if unit_type == "MARKER" else 0,
                         vest_pool_total=1 if unit_type == "VEST" else 0)
    field = create_field(arena["id"], game_mode=game_mode, capacity_max=max(party_size, 6))
    unit = create_equipment(arena["id"], unit_type=unit_type, asset_tag="U-1",
                            deposit_cents=deposit_cents, condition_grade=condition_grade)
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=party_size,
        window_start=clock, window_end="2026-06-15T11:00:00Z",
    )
    if game_mode == "PAINTBALL":
        referee = create_referee(arena["id"], certified_paintball=True)
        assign_referee(arena["id"], booking["id"], referee["id"])
    rental = reserve_rental(arena["id"], booking["id"], unit["id"])
    check_in_booking(booking["id"], party_size)
    return arena, field, unit, booking, rental


# ─── Tier 4: Booking driven to COMPLETED ────────────────────────────────────
def complete_booking(booking_id):
    """Complete a CHECKED_IN booking. Returns the completed booking."""
    return get_success_data(api_client.complete_booking(booking_id, FM))


def setup_completed_booking(clock=CLOCK_BASE, party_size=4, game_mode="LASER_TAG",
                            field_overrides=None):
    """Arena + LASER_TAG field + WALK_IN booking driven all the way to COMPLETED
    (no rentals, no referee needed). Returns (arena, field, booking)."""
    fo = dict(field_overrides or {})
    fo.setdefault("game_mode", game_mode)
    fo.setdefault("capacity_max", max(party_size, 8))
    arena, field = setup_arena_and_field(clock=clock, field_overrides=fo)
    booking = create_confirmed_booking(
        arena, field, booking_type="WALK_IN", party_size=party_size,
        window_start=clock, window_end="2026-06-15T10:00:00Z",
    )
    check_in_booking(booking["id"], party_size)
    completed = complete_booking(booking["id"])
    return arena, field, completed


# ─── Tier 5: Leagues in lifecycle states ────────────────────────────────────
def create_league(arena_id, total_rounds=1, **overrides):
    """Create a DRAFT league. Returns the league."""
    return get_success_data(
        api_client.create_league(create_league_payload(arena_id, total_rounds=total_rounds, **overrides), LD)
    )


def open_league(league_id):
    """Open a league (DRAFT -> OPEN, round 1). Returns the opened league."""
    return get_success_data(api_client.open_league(league_id, LD))


def setup_open_league(arena_id=None, total_rounds=1, clock=CLOCK_BASE, **overrides):
    """Arena + a League in OPEN at round 1. Returns (arena, league)."""
    if arena_id is None:
        arena = create_arena(clock=clock)
        arena_id = arena["id"]
    else:
        arena = get_success_data(api_client.get_arena(arena_id, AM))
    league = create_league(arena_id, total_rounds=total_rounds, **overrides)
    league = open_league(league["id"])
    return arena, league


def setup_round_locked_league(total_rounds=2, clock=CLOCK_BASE, **overrides):
    """League opened at round 1 then locked (ROUND_LOCKED at round 1, no matches).
    Returns (arena, league_after_lock)."""
    arena, league = setup_open_league(total_rounds=total_rounds, clock=clock, **overrides)
    locked = get_success_data(
        api_client.lock_round(league["id"], {"expected_league_version": league["version"]}, LD)
    )
    return arena, locked
