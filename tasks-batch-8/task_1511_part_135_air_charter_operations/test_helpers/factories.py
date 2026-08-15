"""Payload factories — one per entity, input fields only (PRD section 3)."""

DEFAULTS = {
    "OWNER_NAME": "Owner A",
    "OWNER_EMAIL": "owner@example.com",
    "REVENUE_SHARE_PCT": 80,
    "TAIL_NUMBER": "N100AA",
    "CATEGORY": "LIGHT_JET",
    "HOME_BASE": "KLAX",
    "SEATS": 8,
    "HOURLY_RATE_CENTS": 240000,
    "CREW_NAME": "Pic One",
    "CUSTOMER_NAME": "Cust One",
    "CUSTOMER_EMAIL": "cust@example.com",
    "ORIGIN": "KLAX",
    "DESTINATION": "KTEB",
    "DEPARTURE_AT": "2026-08-10T10:00:00Z",
}


def create_aircraft_owner_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["OWNER_NAME"],
        "contact_email": DEFAULTS["OWNER_EMAIL"],
        "revenue_share_pct": DEFAULTS["REVENUE_SHARE_PCT"],
        "guarantee_cents_per_block_min": 0,
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_payload(owner_id: str, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "tail_number": DEFAULTS["TAIL_NUMBER"],
        "category": DEFAULTS["CATEGORY"],
        "home_base_icao": DEFAULTS["HOME_BASE"],
        "seats": DEFAULTS["SEATS"],
        "hourly_rate_cents": DEFAULTS["HOURLY_RATE_CENTS"],
        "on_ops_spec": True,
        "initial_airframe_minutes": 0,
        "next_check_due_minutes": 60000,
    }
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CREW_NAME"],
        "base_icao": DEFAULTS["HOME_BASE"],
        "qualified_categories": [DEFAULTS["CATEGORY"]],
    }
    defaults.update(overrides)
    return defaults


def create_trip_request_payload(**overrides) -> dict:
    defaults = {
        "customer_name": DEFAULTS["CUSTOMER_NAME"],
        "customer_email": DEFAULTS["CUSTOMER_EMAIL"],
        "requested_category": DEFAULTS["CATEGORY"],
        "origin_icao": DEFAULTS["ORIGIN"],
        "destination_icao": DEFAULTS["DESTINATION"],
        "departure_at": DEFAULTS["DEPARTURE_AT"],
        "passenger_count": 0,
        "international": False,
    }
    defaults.update(overrides)
    return defaults


def create_quote_leg_payload(trip_request_id: str, **overrides) -> dict:
    defaults = {
        "trip_request_id": trip_request_id,
        "seq_no": 1,
        "leg_type": "REVENUE",
        "origin_icao": DEFAULTS["ORIGIN"],
        "destination_icao": DEFAULTS["DESTINATION"],
        "block_minutes": 60,
        "fuel_stop": False,
    }
    defaults.update(overrides)
    return defaults


def create_aircraft_assignment_payload(trip_request_id: str, aircraft_id: str,
                                       expected_trip_request_version: int, **overrides) -> dict:
    defaults = {
        "trip_request_id": trip_request_id,
        "aircraft_id": aircraft_id,
        "expected_trip_request_version": expected_trip_request_version,
    }
    defaults.update(overrides)
    return defaults


def create_crew_assignment_payload(trip_request_id: str, crew_member_id: str, **overrides) -> dict:
    defaults = {
        "trip_request_id": trip_request_id,
        "crew_member_id": crew_member_id,
        "duty_role": "PIC",
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_window_payload(aircraft_id: str, **overrides) -> dict:
    defaults = {
        "aircraft_id": aircraft_id,
        "window_type": "ANNUAL",
        "starts_at": "2026-08-05T00:00:00Z",
        "ends_at": "2026-08-05T06:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_passenger_payload(trip_request_id: str, **overrides) -> dict:
    defaults = {
        "trip_request_id": trip_request_id,
        "full_name": "Pax One",
        "date_of_birth": "1980-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_overflight_permit_payload(trip_request_id: str, **overrides) -> dict:
    defaults = {
        "trip_request_id": trip_request_id,
        "country_code": "MX",
        "permit_type": "LANDING",
        "required": True,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(trip_request_id: str, **overrides) -> dict:
    defaults = {
        "trip_request_id": trip_request_id,
        "payment_type": "BALANCE",
        "amount_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_flight_log_payload(trip_request_id: str, quote_leg_id: str, **overrides) -> dict:
    defaults = {
        "trip_request_id": trip_request_id,
        "quote_leg_id": quote_leg_id,
        "actual_block_minutes": 60,
        "departed_at": "2026-08-10T10:00:00Z",
        "arrived_at": "2026-08-10T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_compliance_finding_payload(subject_type: str, subject_id: str, **overrides) -> dict:
    defaults = {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "finding_code": "OPSPEC-A001",
        "grounding": True,
        "notes": "finding notes",
    }
    defaults.update(overrides)
    return defaults


def create_weather_advisory_payload(**overrides) -> dict:
    defaults = {
        "station_icao": DEFAULTS["ORIGIN"],
        "severity": "SIGMET",
        "starts_at": "2026-08-03T00:00:00Z",
        "ends_at": "2026-08-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
