"""Payload factories — one per entity, input fields only (PRD §3).

Required vs optional follows the PRD:
- Field: turnaround_minutes optional (default 0)
- PartyPackage: included_ammo_balls, discount_pct, active optional
- Booking: package_id optional
- WaiverProfile: guardian_name optional
- EquipmentUnit: condition_grade optional (default A)
- Rental: damage_fee_cents supplied only at return
- AddOnOrder: ammo_balls, co2_tanks, misc_cents optional (default 0)
- Referee: certified_paintball optional (default false)
- League: win_points, draw_points optional
"""

from .constants import CLOCK_BASE


def create_arena_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Arena",
        "marker_pool_total": 0,
        "vest_pool_total": 0,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(arena_id: str, to_iso8601: str = CLOCK_BASE, **overrides) -> dict:
    defaults = {"arena_id": arena_id, "to_iso8601": to_iso8601}
    defaults.update(overrides)
    return defaults


def create_field_payload(arena_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "name": "Test Field",
        "game_mode": "LASER_TAG",
        "capacity_max": 8,
    }
    defaults.update(overrides)
    return defaults


def create_party_package_payload(arena_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "name": "Test Package",
        "included_players": 10,
        "extra_player_fee_cents": 500,
        "base_fee_cents": 9000,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(arena_id: str, field_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "field_id": field_id,
        "booking_type": "WALK_IN",
        "party_size": 4,
        "window_start": CLOCK_BASE,
        "window_end": "2026-06-15T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_waiver_profile_payload(arena_id: str, booking_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "booking_id": booking_id,
        "participant_name": "Test Participant",
        "date_of_birth": "1990-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(arena_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "unit_type": "MARKER",
        "asset_tag": "TAG-1",
        "deposit_cents": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(arena_id: str, booking_id: str, equipment_unit_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "booking_id": booking_id,
        "equipment_unit_id": equipment_unit_id,
    }
    defaults.update(overrides)
    return defaults


def create_add_on_order_payload(arena_id: str, booking_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "booking_id": booking_id,
        "ammo_balls": 0,
        "co2_tanks": 0,
        "misc_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_referee_payload(arena_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "name": "Test Referee",
        "certified_paintball": False,
    }
    defaults.update(overrides)
    return defaults


def create_referee_assignment_payload(arena_id: str, booking_id: str, referee_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "booking_id": booking_id,
        "referee_id": referee_id,
    }
    defaults.update(overrides)
    return defaults


def create_league_payload(arena_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "name": "Test League",
        "total_rounds": 1,
        "win_points": 3,
        "draw_points": 1,
    }
    defaults.update(overrides)
    return defaults


def create_league_match_payload(arena_id: str, league_id: str, booking_id: str, **overrides) -> dict:
    defaults = {
        "arena_id": arena_id,
        "league_id": league_id,
        "booking_id": booking_id,
        "home_team": "Home",
        "away_team": "Away",
    }
    defaults.update(overrides)
    return defaults
