"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_customer_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "email": f"customer{n}@example.com",
        "full_name": f"Test Customer {n}",
        "customer_type": "PRIVATE",
    }
    defaults.update(overrides)
    return defaults


def create_venue_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["VENUE_NAME"],
        "address": TEST_DEFAULTS["VENUE_ADDRESS"],
        "venue_type": "OUTDOOR",
        "water_access": True,
        "surface_type": "GRASS",
        "travel_zone": "ZONE_A",
        "distance_miles": 10,
        "max_guest_capacity": 100,
        "requires_animal_permit": False,
        "requires_handwash_stations": True,
    }
    defaults.update(overrides)
    return defaults


def create_animal_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Gogo"),
        "species": "GOAT",
        "weight_class": "SMALL",
        "temperament_tier": 3,
        "base_event_fee_cents": TEST_DEFAULTS["GOAT_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_health_record_payload(**overrides) -> dict:
    defaults = {
        "exam_date": TEST_DEFAULTS["CERT_EXAM_DATE"],
        "result": "PASS",
        "valid_until": TEST_DEFAULTS["CERT_VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def create_handler_payload(**overrides) -> dict:
    defaults = {
        "name": _uniq("Hank"),
        "certifications": ["FIRST_AID"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(**overrides) -> dict:
    defaults = {
        "venue_id": None,  # must be supplied
        "start_time": TEST_DEFAULTS["EVENT_START"],
        "end_time": TEST_DEFAULTS["EVENT_END"],
        "guest_count": 20,
        "child_guest_count": 0,
        "booking_type": "PRIVATE_PARTY",
        "planned_handwash_stations": 1,
    }
    defaults.update(overrides)
    return defaults


def create_insurance_certificate_payload(**overrides) -> dict:
    n = next(_counter)
    defaults = {
        "provider": "Acme Mutual",
        "policy_number": f"POL-{n}",
        "coverage_amount_cents": 500000,
        "expires_at": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_booking_animal_payload(**overrides) -> dict:
    defaults = {
        "animal_id": None,  # must be supplied
        "role": "PETTING_ZOO",
    }
    defaults.update(overrides)
    return defaults


def create_staff_assignment_payload(**overrides) -> dict:
    defaults = {
        "handler_id": None,  # must be supplied
        "role": "LEAD",
    }
    defaults.update(overrides)
    return defaults


def create_addon_payload(**overrides) -> dict:
    defaults = {
        "addon_type": "PONY_RIDE",
        "duration_minutes": 30,
        "expected_booking_version": None,  # must be supplied
    }
    defaults.update(overrides)
    return defaults


def create_permit_payload(**overrides) -> dict:
    defaults = {
        "permit_type": "ANIMAL_EXHIBITION",
        "jurisdiction": "County Fair Board",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 1000,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_weather_assessment_payload(**overrides) -> dict:
    defaults = {
        "assessed_at": "2026-06-16T09:30:00Z",
        "forecast_temp_f": 38,
        "forecast_precip_pct": 90,
        "wind_mph": 35,
        "verdict": "MANDATORY_HOLD",
    }
    defaults.update(overrides)
    return defaults
