"""Payload factories — one per entity, input fields only."""
import itertools

_email_counter = itertools.count(1)
_zone_counter = itertools.count(1)


def unique_email() -> str:
    return f"client{next(_email_counter)}@example.com"


def unique_zone_code() -> str:
    return f"Z{next(_zone_counter)}"


def create_travel_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": unique_zone_code(),
        "name": "Zone",
        "base_travel_fee_cents": 0,
        "per_mile_fee_cents": 0,
        "surge_multiplier_bps": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(**overrides) -> dict:
    defaults = {
        "name": "Std",
        "tier": "STANDARD",
        "flat_package_fee_cents": 50000,
        "included_set_minutes": 120,
        "deposit_pct_bps": 2500,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_payload(**overrides) -> dict:
    defaults = {
        "category": "SOUND",
        "label": "PA",
        "unit_fee_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_performer_payload(**overrides) -> dict:
    defaults = {
        "stage_name": "DJ A",
        "act_type": "DJ",
        "genre": "HOUSE",
        "home_zone_id": None,
        "base_set_rate_cents": 200000,
        "overtime_rate_cents_per_15min": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_blackout_payload(**overrides) -> dict:
    defaults = {
        "start_utc": "2026-08-01T10:00:00Z",
        "end_utc": "2026-08-01T14:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_client_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Client A",
        "email": None,
    }
    defaults.update(overrides)
    if defaults.get("email") is None:
        defaults["email"] = unique_email()
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "client_id": None,
        "performer_id": None,
        "package_id": None,
        "event_zone_id": None,
        "event_start_utc": "2026-08-01T20:00:00Z",
        "event_miles_from_home": 0,
        "contracted_set_minutes": 120,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "booking_id": None,
        "kind": "DEPOSIT",
        "amount_cents": 62500,
    }
    defaults.update(overrides)
    return defaults


def create_song_request_payload(**overrides) -> dict:
    defaults = {
        "title": "Song",
        "list_type": "REQUEST",
    }
    defaults.update(overrides)
    return defaults


def create_backup_assignment_payload(**overrides) -> dict:
    defaults = {
        "candidate_performer_id": None,
        "rank": 1,
    }
    defaults.update(overrides)
    return defaults
