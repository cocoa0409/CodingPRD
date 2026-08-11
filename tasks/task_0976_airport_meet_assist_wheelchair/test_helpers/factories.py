"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "AIRPORT_IATA": "TST",
    "AIRPORT_TZ": -300,
    "AIRPORT_MEET_BUFFER": 15,
    "TERMINAL_CODE": "T1",
    "FLIGHT_NO": "UA100",
    "PASSENGER_NAME": "Test Passenger",
    "PASSENGER_DOB": "1980-01-01",
    "AGENT_NAME": "Test Agent",
    "TSA_FAR_FUTURE": "2027-01-01T00:00:00Z",
    "ASSET_TAG": "WC-001",
    "PICKUP_ZONE": "CURB-A",
}


def create_airport_payload(**overrides) -> dict:
    defaults = {
        "iata_code": DEFAULTS["AIRPORT_IATA"],
        "tz_offset_minutes": DEFAULTS["AIRPORT_TZ"],
        "meet_buffer_minutes": DEFAULTS["AIRPORT_MEET_BUFFER"],
    }
    defaults.update(overrides)
    return defaults


def create_terminal_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["TERMINAL_CODE"],
        "requires_secure_escort": False,
    }
    defaults.update(overrides)
    return defaults


def create_segment_payload(**overrides) -> dict:
    defaults = {
        "flight_no": DEFAULTS["FLIGHT_NO"],
        "direction": "ARRIVAL",
        "scheduled_utc": "2026-06-16T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_passenger_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PASSENGER_NAME"],
        "dob": DEFAULTS["PASSENGER_DOB"],
        "mobility_code": "WCHR",
    }
    defaults.update(overrides)
    return defaults


def create_agent_payload(**overrides) -> dict:
    defaults = {
        "display_name": DEFAULTS["AGENT_NAME"],
        "tsa_cleared_until": DEFAULTS["TSA_FAR_FUTURE"],
        "ummr_certified": False,
        "senior_trained": False,
        "wc_certified": True,
        "shift_start_utc": "2026-06-16T08:00:00Z",
        "shift_end_utc": "2026-06-16T20:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_wheelchair_payload(**overrides) -> dict:
    defaults = {
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "chair_class": "MANUAL",
        "is_wchc_rated": False,
    }
    defaults.update(overrides)
    return defaults


def create_assist_request_payload(**overrides) -> dict:
    defaults = {
        "bill_to": "AIRLINE",
        "service_tier": "STANDARD",
        "companion_count": 0,
    }
    defaults.update(overrides)
    return defaults


def create_leg_payload(**overrides) -> dict:
    defaults = {
        "leg_kind": "MEET_ARRIVAL",
        "pickup_zone": DEFAULTS["PICKUP_ZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "kind": "FALL",
        "severity": "MINOR",
        "description": "test incident",
    }
    defaults.update(overrides)
    return defaults
