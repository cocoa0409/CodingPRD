"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the client-supplied (source: input) fields for a
create call. System and computed fields are never included. FK fields that the
PRD names in the create payload (venue_id, room_id, customer_id, etc.) are
required arguments so callers always thread real ids.
"""
from .constants import PEAK_START_MINUTE, PEAK_END_MINUTE


def create_venue_payload(**overrides) -> dict:
    """POST /venues input. Required: name, timezone, peak_start_minute, peak_end_minute.
    Optional policy levers fall back to PRD defaults when omitted (so they are NOT
    set here unless overridden)."""
    defaults = {
        "name": "Test Venue",
        "timezone": "UTC",
        "peak_start_minute": PEAK_START_MINUTE,
        "peak_end_minute": PEAK_END_MINUTE,
        "peak_multiplier": 1.5,
        "deposit_pct": 0.2,
        "cancellation_cutoff_hours": 24,
        "grace_minutes": 15,
        "overage_grace_minutes": 10,
    }
    defaults.update(overrides)
    return defaults


def create_room_type_payload(venue_id, **overrides) -> dict:
    """POST /room-types input. Required: venue_id, name, capacity, base_hourly_rate_cents."""
    defaults = {
        "venue_id": venue_id,
        "name": "LARGE",
        "capacity": 12,
        "base_hourly_rate_cents": 6000,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(venue_id, room_type_id, **overrides) -> dict:
    """POST /rooms input. Required: venue_id, room_type_id, label."""
    defaults = {
        "venue_id": venue_id,
        "room_type_id": room_type_id,
        "label": "Room 1",
    }
    defaults.update(overrides)
    return defaults


def create_group_package_payload(venue_id, included_room_type_id, **overrides) -> dict:
    """POST /group-packages input. Required: venue_id, name, flat_price_cents,
    included_hours, included_room_type_id."""
    defaults = {
        "venue_id": venue_id,
        "name": "Bash",
        "flat_price_cents": 20000,
        "included_hours": 2.0,
        "included_room_type_id": included_room_type_id,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    """POST /customers input. Required: full_name, email, phone."""
    defaults = {
        "full_name": "Test Customer",
        "email": "customer@example.com",
        "phone": "5551234567",
    }
    defaults.update(overrides)
    return defaults


def create_song_payload(venue_id, **overrides) -> dict:
    """POST /songs input. Required: venue_id, title, artist, duration_seconds, language."""
    defaults = {
        "venue_id": venue_id,
        "title": "Test Song",
        "artist": "Test Artist",
        "duration_seconds": 200,
        "language": "EN",
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(venue_id, room_id, customer_id, expected_room_version,
                               slot_start_utc, slot_end_utc, **overrides) -> dict:
    """POST /reservations input. Required: venue_id, room_id, customer_id, party_size,
    slot_start_utc, slot_end_utc, expected_room_version. group_package_id optional."""
    defaults = {
        "venue_id": venue_id,
        "room_id": room_id,
        "customer_id": customer_id,
        "party_size": 4,
        "slot_start_utc": slot_start_utc,
        "slot_end_utc": slot_end_utc,
        "expected_room_version": expected_room_version,
    }
    defaults.update(overrides)
    return defaults


def create_extension_payload(new_slot_end_utc, expected_reservation_version, **overrides) -> dict:
    """POST /reservations/{id}/extensions input. Required: new_slot_end_utc,
    expected_reservation_version."""
    defaults = {
        "new_slot_end_utc": new_slot_end_utc,
        "expected_reservation_version": expected_reservation_version,
    }
    defaults.update(overrides)
    return defaults


def create_queue_entry_payload(song_id, **overrides) -> dict:
    """POST /reservations/{id}/queue input. Required: song_id. priority optional (default 100)."""
    defaults = {
        "song_id": song_id,
    }
    defaults.update(overrides)
    return defaults


def create_fb_order_payload(**overrides) -> dict:
    """POST /reservations/{id}/fb-orders input. Required: description, unit_price_cents, quantity."""
    defaults = {
        "description": "1x Item",
        "unit_price_cents": 1000,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults
