"""Payload factories - one per entity, input fields only."""
from itertools import count

from .constants import TEST_DEFAULTS

_agency_code_seq = count(1)


def next_agency_code() -> str:
    """A fresh, unique buyer code; agency_code must be unique across advertisers."""
    return "HLF-{:03d}".format(next(_agency_code_seq))


def create_client_payload(**overrides) -> dict:
    payload = {
        "name": "Harborline Foods",
        "agency_code": next_agency_code(),
        "billing_email": "ap@harborline.example",
    }
    payload.update(overrides)
    return payload


def create_project_payload(client_id, **overrides) -> dict:
    payload = {
        "client_id": client_id,
        "title": "Winter Warmth",
        "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
        "delivery_deadline_utc": TEST_DEFAULTS["DELIVERY_DEADLINE_UTC"],
    }
    payload.update(overrides)
    return payload


def create_brief_payload(**overrides) -> dict:
    payload = {
        "tempo_bpm": 110,
        "mood_tags": ["cosy"],
        "target_markets": ["US_NATIONAL"],
        "required_lengths": [30],
    }
    payload.update(overrides)
    return payload


def create_composer_payload(**overrides) -> dict:
    payload = {"display_name": "Ada Rivers", "pro_affiliation": "ASCAP"}
    payload.update(overrides)
    return payload


def create_demo_payload(**overrides) -> dict:
    payload = {
        "title": "Cut One",
        "demo_fee_cents": TEST_DEFAULTS["DEMO_FEE_CENTS"],
        "submitted_length_seconds": 30,
    }
    payload.update(overrides)
    return payload


def create_musician_payload(**overrides) -> dict:
    payload = {
        "full_name": "Mia Vance",
        "instrument": "DRUMS",
        "scale_hourly_cents": TEST_DEFAULTS["SCALE_HOURLY_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_studio_room_payload(**overrides) -> dict:
    payload = {
        "name": "Room A",
        "hourly_rate_cents": TEST_DEFAULTS["ROOM_HOURLY_RATE_CENTS"],
        "capacity_players": TEST_DEFAULTS["ROOM_CAPACITY_PLAYERS"],
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_session_call_payload(project_id, studio_room_id, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "studio_room_id": studio_room_id,
        "scheduled_start_utc": "2026-09-10T09:00:00Z",
        "scheduled_end_utc": "2026-09-10T13:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_booking_payload(musician_id, **overrides) -> dict:
    payload = {"musician_id": musician_id, "is_leader": False, "doubles_count": 0}
    payload.update(overrides)
    return payload


def create_license_deal_payload(project_id, demo_id, expected_project_version, **overrides) -> dict:
    payload = {
        "project_id": project_id,
        "demo_id": demo_id,
        "license_structure": "BUYOUT",
        "market_codes": ["US_NATIONAL"],
        "creative_fee_cents": TEST_DEFAULTS["CREATIVE_FEE_CENTS"],
        "expected_project_version": expected_project_version,
    }
    payload.update(overrides)
    return payload


def create_counter_payload(**overrides) -> dict:
    payload = {"counter_note": "drop the regional market", "market_codes": ["US_NATIONAL"]}
    payload.update(overrides)
    return payload


def create_reuse_extension_payload(market_code, expected_license_deal_version, **overrides) -> dict:
    payload = {
        "market_code": market_code,
        "expected_license_deal_version": expected_license_deal_version,
    }
    payload.update(overrides)
    return payload


def create_cue_entry_payload(composer_id, **overrides) -> dict:
    payload = {"composer_id": composer_id, "role": "COMPOSER", "declared_weight": 1}
    payload.update(overrides)
    return payload


def create_stems_payload(**overrides) -> dict:
    payload = {
        "stem_names": ["DRUMS", "BASS", "KEYS", "VOX", "MIX"],
        "lengths_seconds": [30],
    }
    payload.update(overrides)
    return payload


def create_library_track_payload(**overrides) -> dict:
    payload = {
        "title": "Amber Lift",
        "blanket_fee_cents": 200_000,
        "per_market_fee_cents": 30_000,
        "max_markets": 3,
        "min_length_seconds": 15,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload
