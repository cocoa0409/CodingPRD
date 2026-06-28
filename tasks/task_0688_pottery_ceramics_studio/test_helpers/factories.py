"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Email values must be unique per member; callers that
create multiple members in one test should pass distinct emails.
"""
import itertools

_email_counter = itertools.count(1)


def _unique_email(prefix: str = "member") -> str:
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": _unique_email(),
        "full_name": "Test Member",
        "phone": "555-0000",
    }
    defaults.update(overrides)
    return defaults


def create_paint_bar_item_payload(**overrides) -> dict:
    defaults = {
        "sku": f"GLZ-{next(_email_counter)}",
        "name": "Test Glaze",
        "category": "GLAZE",
        "unit_price_cents": 500,
        "reorder_threshold": 5,
    }
    defaults.update(overrides)
    return defaults


def create_visit_payload(**overrides) -> dict:
    defaults = {
        "party_size": 1,
        "visit_type": "WALK_IN",
    }
    defaults.update(overrides)
    return defaults


def create_piece_payload(**overrides) -> dict:
    defaults = {
        "sku": "MUG-12OZ",
        "name": "Mug",
        "bisque_price_cents": 3000,
        "firing_temp": "CONE_06",
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "kiln_name": "Kiln A",
        "firing_temp": "CONE_06",
        "capacity_slots": 4,
        "turnaround_hours": 48,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "package_tier": "BASIC",
        "guest_count": 6,
        "scheduled_for": "2026-09-01T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_series_payload(**overrides) -> dict:
    defaults = {
        "title": "Wheel Throwing 101",
        "session_count": 4,
        "seat_capacity": 5,
        "price_cents": 12000,
        "starts_at": "2026-07-01T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_load_payload(bisque_piece_id: str, expected_kiln_batch_version: int, **overrides) -> dict:
    defaults = {
        "bisque_piece_id": bisque_piece_id,
        "expected_kiln_batch_version": expected_kiln_batch_version,
    }
    defaults.update(overrides)
    return defaults


def create_consume_payload(paint_bar_item_id: str, qty: int, **overrides) -> dict:
    defaults = {
        "paint_bar_item_id": paint_bar_item_id,
        "qty": qty,
    }
    defaults.update(overrides)
    return defaults
