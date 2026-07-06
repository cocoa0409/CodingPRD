"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "SERIES_NAME": "Test Supper Series",
    "VENUE_NAME": "Test Loft",
    "VENUE_ADDRESS": "1 Test Street",
    "CHEF_NAME": "Test Chef",
    "GUEST_NAME": "Test Guest",
    "EVENT_TITLE": "Test Dinner",
    "SEAT_PRICE_CENTS": 10000,
    "DEPOSIT_PCT": 0.25,
    "SEAT_CAPACITY": 2,
    "EVENT_START": "2026-03-15T18:00:00Z",
    "EVENT_END": "2026-03-15T22:00:00Z",
    "BOOKING_DEADLINE": "2026-03-14T00:00:00Z",
}


def create_series_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SERIES_NAME"],
        "cadence": "WEEKLY",
        "theme": "Seasonal",
        "default_seat_capacity": DEFAULTS["SEAT_CAPACITY"],
        "base_seat_price_cents": DEFAULTS["SEAT_PRICE_CENTS"],
        "default_deposit_pct": DEFAULTS["DEPOSIT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENUE_NAME"],
        "address": DEFAULTS["VENUE_ADDRESS"],
        "max_capacity": 50,
        "corkage_policy": "ALLOWED",
    }
    defaults.update(overrides)
    return defaults


def create_chef_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CHEF_NAME"],
        "specialty": "Seasonal",
    }
    defaults.update(overrides)
    return defaults


def create_guest_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["GUEST_NAME"],
        "email": "guest@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(series_id, venue_id, chef_id, **overrides) -> dict:
    defaults = {
        "series_id": series_id,
        "venue_id": venue_id,
        "chef_id": chef_id,
        "title": DEFAULTS["EVENT_TITLE"],
        "event_start": DEFAULTS["EVENT_START"],
        "event_end": DEFAULTS["EVENT_END"],
        "booking_deadline": DEFAULTS["BOOKING_DEADLINE"],
        "table_mode": "COMMUNAL",
        "seat_capacity": DEFAULTS["SEAT_CAPACITY"],
        "seat_price_cents": DEFAULTS["SEAT_PRICE_CENTS"],
        "deposit_pct": DEFAULTS["DEPOSIT_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_menu_course_payload(**overrides) -> dict:
    defaults = {
        "course_number": 1,
        "name": "Test Course",
        "contains_allergens": [],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(event_id, guest_id, seat_ids, party_size=None, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "guest_id": guest_id,
        "party_size": party_size if party_size is not None else len(seat_ids),
        "seat_ids": seat_ids,
    }
    defaults.update(overrides)
    return defaults


def create_waitlist_payload(guest_id, party_size=1, **overrides) -> dict:
    defaults = {
        "guest_id": guest_id,
        "party_size": party_size,
    }
    defaults.update(overrides)
    return defaults
