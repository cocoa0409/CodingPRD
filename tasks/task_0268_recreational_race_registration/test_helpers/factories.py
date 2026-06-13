"""Payload factories — one per entity, input fields only (PRD §3, §4).

Required fields get sensible defaults; optional fields are omitted unless
overridden so the server applies its declared defaults.
"""
from .constants import (
    OPENS_UTC, CLOSES_UTC, RACE_DATE_UTC, TIER_REGULAR_FROM, REGULAR_BASE_CENTS,
)

_email_counter = [0]


def unique_email(prefix: str = "runner") -> str:
    _email_counter[0] += 1
    return f"{prefix}{_email_counter[0]}@example.com"


def participant_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test Runner",
        "birthdate": "1990-01-01",
        "gender": "M",
    }
    defaults.update(overrides)
    return defaults


def event_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Event",
        "race_date_utc": RACE_DATE_UTC,
        "registration_opens_utc": OPENS_UTC,
        "registration_closes_utc": CLOSES_UTC,
    }
    defaults.update(overrides)
    return defaults


def distance_payload(**overrides) -> dict:
    defaults = {
        "label": "FIVE_K",
        "distance_km": 5.0,
        "capacity_total": 50,
    }
    defaults.update(overrides)
    return defaults


def wave_payload(**overrides) -> dict:
    defaults = {
        "name": "Wave 1",
        "start_offset_seconds": 0,
        "wave_capacity": 50,
        "corral_capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def pricing_tier_payload(**overrides) -> dict:
    defaults = {
        "tier_name": "REGULAR",
        "effective_from_utc": TIER_REGULAR_FROM,
        "base_price_cents": REGULAR_BASE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def registration_payload(event_id, distance_id, wave_id, participant_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "distance_id": distance_id,
        "wave_id": wave_id,
        "participant_id": participant_id,
    }
    defaults.update(overrides)
    return defaults


def pledge_payload(registration_id, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "donor_name": "Donor",
        "amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def transfer_request_payload(registration_id, to_participant_id, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "to_participant_id": to_participant_id,
    }
    defaults.update(overrides)
    return defaults


def packet_pickup_payload(registration_id, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "picked_up_by_name": "Self",
    }
    defaults.update(overrides)
    return defaults


def result_payload(registration_id, distance_id, gun_start_clock_seconds,
                   mat_cross_clock_seconds, finish_clock_seconds, **overrides) -> dict:
    defaults = {
        "registration_id": registration_id,
        "distance_id": distance_id,
        "gun_start_clock_seconds": gun_start_clock_seconds,
        "mat_cross_clock_seconds": mat_cross_clock_seconds,
        "finish_clock_seconds": finish_clock_seconds,
    }
    defaults.update(overrides)
    return defaults
