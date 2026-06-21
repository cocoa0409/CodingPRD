"""Payload factories — one per entity, input fields only (PRD Sections 3.1-3.12)."""

DEFAULTS = {
    "VENUE_NAME": "Test Venue",
    "ROOM_NAME": "Test Room",
    "PACKAGE_THEME": "Dino",
    "BASE_PRICE_CENTS": 30000,
    "INCLUDED_CHILDREN": 8,
    "PER_EXTRA_CHILD_CENTS": 1500,
    "BASE_DURATION_MINUTES": 120,
    "DEPOSIT_PCT": 0.25,
    "MAX_CAPACITY": 20,
    "BUFFER_MINUTES": 30,
    "STAFF_NAME": "Test Staff",
    "EVENT_START_UTC": "2026-07-01T10:00:00Z",
    "CHILDREN_COUNT": 8,
    "CHILD_NAME": "Test Child",
    "SIGNATURE": "sig",
    "CLOCK_BASE_UTC": "2026-06-25T09:00:00Z",
}


def create_venue_payload(**overrides) -> dict:
    defaults = {"name": DEFAULTS["VENUE_NAME"], "weather_dependent": False}
    defaults.update(overrides)
    return defaults


def create_room_payload(venue_id: str, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "name": DEFAULTS["ROOM_NAME"],
        "max_capacity": DEFAULTS["MAX_CAPACITY"],
        "buffer_minutes": DEFAULTS["BUFFER_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(venue_id: str, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "theme": DEFAULTS["PACKAGE_THEME"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "included_children": DEFAULTS["INCLUDED_CHILDREN"],
        "per_extra_child_cents": DEFAULTS["PER_EXTRA_CHILD_CENTS"],
        "base_duration_minutes": DEFAULTS["BASE_DURATION_MINUTES"],
        "deposit_pct": DEFAULTS["DEPOSIT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_member_payload(venue_id: str, **overrides) -> dict:
    defaults = {
        "venue_id": venue_id,
        "full_name": DEFAULTS["STAFF_NAME"],
        "skills": [],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(room_id: str, package_id: str, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "package_id": package_id,
        "event_start_utc": DEFAULTS["EVENT_START_UTC"],
        "children_count": DEFAULTS["CHILDREN_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_add_on_payload(kind: str, unit_price_cents: int, **overrides) -> dict:
    defaults = {"kind": kind, "unit_price_cents": unit_price_cents, "quantity": 1}
    defaults.update(overrides)
    return defaults


def create_guest_party_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_waiver_payload(child_name: str = None, **overrides) -> dict:
    defaults = {"child_name": child_name or DEFAULTS["CHILD_NAME"]}
    defaults.update(overrides)
    return defaults


def create_staff_assignment_payload(staff_member_id: str, role_on_event: str, **overrides) -> dict:
    defaults = {"staff_member_id": staff_member_id, "role_on_event": role_on_event}
    defaults.update(overrides)
    return defaults


def create_payment_payload(direction: str, amount_cents: int, **overrides) -> dict:
    defaults = {"direction": direction, "amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
