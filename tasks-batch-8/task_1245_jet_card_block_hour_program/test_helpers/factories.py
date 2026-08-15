"""Payload factories — one per entity, input fields only."""

from .constants import DEFAULT_PROGRAM

_counter = {"n": 0}


def _uniq(prefix: str) -> str:
    _counter["n"] += 1
    return f"{prefix}-{_counter['n']:04d}"


def create_program_payload(**overrides) -> dict:
    defaults = dict(DEFAULT_PROGRAM)
    defaults["program_code"] = _uniq("PROG")
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": f"{_uniq('member')}@x.com",
        "full_name": "Test Member",
        "tier": "INDIVIDUAL",
        "home_base_icao": "KTEB",
    }
    defaults.update(overrides)
    return defaults


def create_card_payload(program_id: str, **overrides) -> dict:
    defaults = {"program_id": program_id}
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(**overrides) -> dict:
    defaults = {
        "tail_number": _uniq("N"),
        "category": "LIGHT",
        "home_base_icao": "KTEB",
        "seats": 6,
        "reposition_rate_cents_per_nm": 80,
    }
    defaults.update(overrides)
    return defaults


def create_trip_payload(**overrides) -> dict:
    defaults = {
        "trip_kind": "ONE_WAY",
        "departure_icao": "KTEB",
        "arrival_icao": "KPBI",
        "requested_departure_utc": "2026-06-15T15:00:00Z",
        "pax_count": 4,
        "requested_category": "LIGHT",
    }
    defaults.update(overrides)
    return defaults


def create_peak_window_payload(**overrides) -> dict:
    defaults = {
        "window_start_utc": "2026-12-01T00:00:00Z",
        "window_end_utc": "2026-12-08T00:00:00Z",
        "label": "Peak Window",
    }
    defaults.update(overrides)
    return defaults


def create_blackout_window_payload(**overrides) -> dict:
    defaults = {
        "window_start_utc": "2026-07-01T00:00:00Z",
        "window_end_utc": "2026-07-10T00:00:00Z",
        "applies_to_category": "LIGHT",
        "reason": "Maintenance",
    }
    defaults.update(overrides)
    return defaults


def create_refund_payload(expected_card_version: int, **overrides) -> dict:
    defaults = {"expected_card_version": expected_card_version}
    defaults.update(overrides)
    return defaults


def create_fractional_upgrade_payload(expected_card_version: int, **overrides) -> dict:
    defaults = {"expected_card_version": expected_card_version}
    defaults.update(overrides)
    return defaults
