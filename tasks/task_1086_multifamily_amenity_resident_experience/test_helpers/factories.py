"""Payload factories — one per entity, input fields only.

Each factory returns a dict of the resource's ``source: input`` fields with
sensible defaults; ``**overrides`` replace any of them. Optional fields with a
server-side default are omitted unless overridden.
"""

DEFAULTS = {
    "PROPERTY_NAME": "Test Property",
    "ADDRESS": "1 Test St",
    "GUEST_PARKING_CAPACITY": 5,
    "UNIT_NUMBER": "101",
    "BEDROOMS": 1,
    "RESIDENT_NAME": "Test Resident",
    "AMENITY_NAME": "Test Amenity",
    "BASE_RATE": 4000,
    "VENDOR_NAME": "Test Vendor",
    "HOURLY_RATE": 8000,
    "EVENT_TITLE": "Test Event",
    "SURVEY_TITLE": "Test Survey",
    "CARRIER": "UPS",
    "GUEST_NAME": "Test Guest",
}


def create_property_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PROPERTY_NAME"],
        "address": DEFAULTS["ADDRESS"],
        "guest_parking_capacity": DEFAULTS["GUEST_PARKING_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "unit_number": DEFAULTS["UNIT_NUMBER"],
        "bedrooms": DEFAULTS["BEDROOMS"],
    }
    defaults.update(overrides)
    return defaults


def create_resident_payload(unit_id, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "full_name": DEFAULTS["RESIDENT_NAME"],
        "email": "resident@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_amenity_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "name": DEFAULTS["AMENITY_NAME"],
        "amenity_type": "GYM",
        "capacity": 1,
        "base_rate_cents_per_hour": DEFAULTS["BASE_RATE"],
        "open_minute": 0,
        "close_minute": 1440,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(amenity_id, resident_id, start_at, end_at, expected_amenity_version, **overrides) -> dict:
    defaults = {
        "amenity_id": amenity_id,
        "resident_id": resident_id,
        "start_at": start_at,
        "end_at": end_at,
        "expected_amenity_version": expected_amenity_version,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(property_id, title, start_at, end_at, capacity, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "title": title,
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["VENDOR_NAME"],
        "trades": ["PLUMBING"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_service_request_payload(unit_id, resident_id, trade, description, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "resident_id": resident_id,
        "trade": trade,
        "description": description,
    }
    defaults.update(overrides)
    return defaults


def create_package_payload(resident_id, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "carrier": DEFAULTS["CARRIER"],
    }
    defaults.update(overrides)
    return defaults


def create_guest_pass_payload(resident_id, arrival_at, expected_departure_at, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "guest_name": DEFAULTS["GUEST_NAME"],
        "arrival_at": arrival_at,
        "expected_departure_at": expected_departure_at,
    }
    defaults.update(overrides)
    return defaults


def create_survey_payload(property_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "title": DEFAULTS["SURVEY_TITLE"],
    }
    defaults.update(overrides)
    return defaults


def create_survey_response_payload(resident_id, satisfaction_score, **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "satisfaction_score": satisfaction_score,
    }
    defaults.update(overrides)
    return defaults


def create_rent_charge_payload(amount_cents, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_payment_payload(resident_id, amount_cents, method="ACH", **overrides) -> dict:
    defaults = {
        "resident_id": resident_id,
        "amount_cents": amount_cents,
        "method": method,
    }
    defaults.update(overrides)
    return defaults
