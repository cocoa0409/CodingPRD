"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "STUDIO_NAME": "Echo Labs",
    "ROOM_NAME": "Room A",
    "HOURLY_RATE_CENTS": 6000,
    "BLOCK_RATE_CENTS": 40000,
    "ENGINEER_NAME": "Sam",
    "ENGINEER_RATE_CENTS": 8000,
    "GEAR_NAME": "Vintage Pre",
    "GEAR_DAILY_RATE_CENTS": 1500,
    "CLIENT_NAME": "Band",
    "CLIENT_EMAIL": "band@x.com",
    "START_AT": "2026-07-10T09:00:00Z",
    "END_AT": "2026-07-10T12:30:00Z",
}


def create_studio_payload(**overrides) -> dict:
    """POST /studio — only `name` is required; commercial constants are optional."""
    defaults = {"name": DEFAULTS["STUDIO_NAME"]}
    defaults.update(overrides)
    return defaults


def create_room_payload(studio_id, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "name": DEFAULTS["ROOM_NAME"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "block_rate_cents": DEFAULTS["BLOCK_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_engineer_payload(studio_id, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "full_name": DEFAULTS["ENGINEER_NAME"],
        "tier": "STAFF",
        "hourly_rate_cents": DEFAULTS["ENGINEER_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_gear_item_payload(studio_id, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "name": DEFAULTS["GEAR_NAME"],
        "total_units": 2,
        "daily_rate_cents": DEFAULTS["GEAR_DAILY_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def register_client_payload(studio_id, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "display_name": DEFAULTS["CLIENT_NAME"],
        "email": DEFAULTS["CLIENT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(studio_id, room_id, client_id, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "room_id": room_id,
        "client_id": client_id,
        "booking_kind": "HOURLY",
        "start_at": DEFAULTS["START_AT"],
        "end_at": DEFAULTS["END_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(kind, amount_cents, **overrides) -> dict:
    defaults = {"kind": kind, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_gear_rental_payload(gear_item_id, units, expected_booking_version, **overrides) -> dict:
    defaults = {
        "gear_item_id": gear_item_id,
        "units": units,
        "expected_booking_version": expected_booking_version,
    }
    defaults.update(overrides)
    return defaults


def create_engineer_assignment_payload(engineer_id, **overrides) -> dict:
    defaults = {"engineer_id": engineer_id}
    defaults.update(overrides)
    return defaults


def create_lockout_contract_payload(studio_id, room_id, client_id, **overrides) -> dict:
    defaults = {
        "studio_id": studio_id,
        "room_id": room_id,
        "client_id": client_id,
        "weekday_mask": [1, 3],
        "daily_start_local": "18:00",
        "daily_end_local": "22:00",
        "window_start_date": "2026-07-06T00:00:00Z",
        "window_end_date": "2026-07-08T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def check_out_payload(actual_end_at, **overrides) -> dict:
    defaults = {"actual_end_at": actual_end_at}
    defaults.update(overrides)
    return defaults


def delivery_payload(file_manifest=None, **overrides) -> dict:
    defaults = {"file_manifest": file_manifest if file_manifest is not None else [{"name": "mix.wav", "size": 1000}]}
    defaults.update(overrides)
    return defaults
