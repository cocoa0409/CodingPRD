"""Payload factories — one per entity, input fields only.

Defaults follow the shared geometry/clock conventions (home == venue, distance 0)
so pay assertions depend only on rank/fee/uplift math.
"""
from .constants import (
    HOME_LAT, HOME_LON, VENUE_LAT, VENUE_LON,
    WIDE_WINDOW_START, WIDE_WINDOW_END,
)


def create_league_payload(**overrides) -> dict:
    defaults = {
        "name": "Test League",
        "sport": "BASKETBALL",
        "base_game_fee_cents": 10000,
        "mileage_rate_cents_per_mile": 0,
    }
    defaults.update(overrides)
    return defaults


def create_official_payload(league_id, **overrides) -> dict:
    defaults = {
        "league_id": league_id,
        "full_name": "Test Official",
        "home_lat": HOME_LAT,
        "home_lon": HOME_LON,
    }
    defaults.update(overrides)
    return defaults


def create_availability_payload(official_id, **overrides) -> dict:
    defaults = {
        "official_id": official_id,
        "window_start_utc": WIDE_WINDOW_START,
        "window_end_utc": WIDE_WINDOW_END,
    }
    defaults.update(overrides)
    return defaults


def create_conflict_declaration_payload(official_id, **overrides) -> dict:
    defaults = {
        "official_id": official_id,
        "scope": "TEAM",
    }
    defaults.update(overrides)
    return defaults


def create_game_payload(league_id, **overrides) -> dict:
    defaults = {
        "league_id": league_id,
        "home_team": "Home",
        "away_team": "Away",
        "venue_lat": VENUE_LAT,
        "venue_lon": VENUE_LON,
        "start_utc": "2026-06-20T18:00:00Z",
        "required_crew_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_crew_slot_payload(**overrides) -> dict:
    defaults = {
        "position": "ASSISTANT",
    }
    defaults.update(overrides)
    return defaults


def offer_payload(official_id, expected_game_version, **overrides) -> dict:
    defaults = {
        "official_id": official_id,
        "expected_game_version": expected_game_version,
    }
    defaults.update(overrides)
    return defaults


def accept_payload(expected_game_version, **overrides) -> dict:
    defaults = {
        "expected_game_version": expected_game_version,
    }
    defaults.update(overrides)
    return defaults


def game_version_payload(expected_game_version, **overrides) -> dict:
    """Shared body for lock/settle: just expected_game_version."""
    defaults = {
        "expected_game_version": expected_game_version,
    }
    defaults.update(overrides)
    return defaults


def update_official_payload(expected_official_version, **overrides) -> dict:
    defaults = {
        "expected_official_version": expected_official_version,
    }
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(score, **overrides) -> dict:
    defaults = {
        "score": score,
    }
    defaults.update(overrides)
    return defaults


def create_appeal_payload(**overrides) -> dict:
    defaults = {
        "reason": "Appeal reason",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
