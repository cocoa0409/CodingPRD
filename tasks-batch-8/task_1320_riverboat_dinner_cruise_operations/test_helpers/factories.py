"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "DOCK_NAME": "Pier 9",
    "PARKING_CAPACITY": 10,
    "VESSEL_NAME": "Belle",
    "VESSEL_CAPACITY": 100,
    "TIER_CODE": "STANDARD",
    "BASE_PRICE_CENTS": 8900,
    "GALLEY_LOAD_PER_COVER": 2.5,
    "BAR_PACKAGE_PRICE_CENTS": 4200,
    # A PEAK-season, non-holiday evening departure/return pair (PRD §3.2).
    "DEPART_AT": "2026-08-10T19:00:00Z",
    "RETURN_AT": "2026-08-10T22:00:00Z",
    "CUSTOMER_EMAIL": "guest@example.com",
    "CUSTOMER_NAME": "Guest",
    "PASSENGER_NAME": "Passenger One",
    "PASSENGER_DOB": "1990-01-01",
    "STAFF_NAME": "Crew Member",
    "STAFF_ROLE": "SERVER",
    "WEATHER_SEVERITY": "CANCELLATION_REQUIRED",
    "WINDOW_START": "2026-08-10T00:00:00Z",
    "WINDOW_END": "2026-08-11T00:00:00Z",
    "SLOT_START": "2026-08-10T14:00:00Z",
    "SLOT_END": "2026-08-10T16:00:00Z",
}


def create_dock_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["DOCK_NAME"],
        "parking_capacity": DEFAULTS["PARKING_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_vessel_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VESSEL_NAME"],
        "coast_guard_capacity": DEFAULTS["VESSEL_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_menu_tier_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["TIER_CODE"],
        "base_price_cents": DEFAULTS["BASE_PRICE_CENTS"],
        "galley_load_per_cover": DEFAULTS["GALLEY_LOAD_PER_COVER"],
        "bar_package_price_cents": DEFAULTS["BAR_PACKAGE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_cruise_payload(**overrides) -> dict:
    defaults = {
        "depart_at": DEFAULTS["DEPART_AT"],
        "return_at": DEFAULTS["RETURN_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["CUSTOMER_EMAIL"],
        "full_name": DEFAULTS["CUSTOMER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "party_size": 1,
    }
    defaults.update(overrides)
    return defaults


def create_passenger_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PASSENGER_NAME"],
        "date_of_birth": DEFAULTS["PASSENGER_DOB"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["STAFF_NAME"],
        "role_code": DEFAULTS["STAFF_ROLE"],
    }
    defaults.update(overrides)
    return defaults


def create_staff_assignment_payload(**overrides) -> dict:
    defaults = {
        "assigned_role": DEFAULTS["STAFF_ROLE"],
    }
    defaults.update(overrides)
    return defaults


def create_charter_inquiry_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_weather_event_payload(**overrides) -> dict:
    defaults = {
        "severity": DEFAULTS["WEATHER_SEVERITY"],
        "window_start": DEFAULTS["WINDOW_START"],
        "window_end": DEFAULTS["WINDOW_END"],
    }
    defaults.update(overrides)
    return defaults


def create_dock_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_start": DEFAULTS["SLOT_START"],
        "slot_end": DEFAULTS["SLOT_END"],
    }
    defaults.update(overrides)
    return defaults


def create_parking_pass_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_clock_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults
