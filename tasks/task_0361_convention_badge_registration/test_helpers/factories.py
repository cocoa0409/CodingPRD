"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the input fields the create endpoint accepts,
with sensible defaults that tests override as needed.
"""
import itertools

from .constants import (
    DEFAULT_EVENT_START,
    DEFAULT_EVENT_END,
    DEFAULT_LOTTERY_OPEN,
)

# Monotonic counter to make unique emails / booth codes within one test run.
_counter = itertools.count(1)


def unique_email(prefix: str = "user") -> str:
    return f"{prefix}{next(_counter)}@x.com"


def unique_booth_code(prefix: str = "B") -> str:
    return f"{prefix}{next(_counter)}"


def create_convention_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Convention",
        "event_start_utc": DEFAULT_EVENT_START,
        "event_end_utc": DEFAULT_EVENT_END,
        "total_badge_capacity": 100,
        "lottery_open_utc": DEFAULT_LOTTERY_OPEN,
    }
    defaults.update(overrides)
    return defaults


def create_ticket_type_payload(**overrides) -> dict:
    defaults = {
        "tier": "GENERAL",
        "base_price_cents": 9900,
        "tier_capacity": 100,
    }
    defaults.update(overrides)
    return defaults


def create_attendee_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email("att"),
        "full_name": "Test Attendee",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(convention_id, purchaser_attendee_id, line_items, **overrides) -> dict:
    defaults = {
        "convention_id": convention_id,
        "purchaser_attendee_id": purchaser_attendee_id,
        "line_items": line_items,
    }
    defaults.update(overrides)
    return defaults


def line_item(ticket_type_id, quantity) -> dict:
    """Build a single order line item entry."""
    return {"ticket_type_id": ticket_type_id, "quantity": quantity}


def create_session_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Panel",
        "start_utc": "2026-09-01T10:00:00Z",
        "end_utc": "2026-09-01T11:00:00Z",
        "seat_capacity": 5,
    }
    defaults.update(overrides)
    return defaults


def create_session_reservation_payload(session_id, badge_id, expected_session_version, **overrides) -> dict:
    defaults = {
        "session_id": session_id,
        "badge_id": badge_id,
        "expected_session_version": expected_session_version,
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_entry_payload(attendee_id, **overrides) -> dict:
    defaults = {
        "attendee_id": attendee_id,
        "requested_quantity": 1,
        "group_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_exhibitor_payload(convention_id, **overrides) -> dict:
    defaults = {
        "convention_id": convention_id,
        "company_name": "Test Vendor",
        "contact_email": unique_email("exh"),
    }
    defaults.update(overrides)
    return defaults


def create_booth_payload(**overrides) -> dict:
    defaults = {
        "booth_code": unique_booth_code(),
        "zone": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_booth_booking_payload(booth_id, exhibitor_id, **overrides) -> dict:
    defaults = {
        "booth_id": booth_id,
        "exhibitor_id": exhibitor_id,
        "occupy_start_utc": "2026-09-01T00:00:00Z",
        "occupy_end_utc": "2026-09-02T00:00:00Z",
        "requested_days": 1,
    }
    defaults.update(overrides)
    return defaults
