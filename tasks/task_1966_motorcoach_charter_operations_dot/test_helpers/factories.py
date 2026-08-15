"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
import itertools

from .constants import TEST_DEFAULTS

# Per-process uniquifiers for fleet-unique fields (unit_number, cdl_number).
_unit_counter = itertools.count(1)
_cdl_counter = itertools.count(1)
_email_counter = itertools.count(1)


def create_customer_payload(**overrides) -> dict:
    n = next(_email_counter)
    defaults = {
        "company_name": f"Test Customer {n}",
        "contact_email": f"customer{n}@example.com",
        "contact_phone": f"555-{1000 + n}",
        "billing_address": f"{1000 + n} Main St",
    }
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    n = next(_unit_counter)
    defaults = {
        "unit_number": f"MC-{n:04d}",
        "make_model": "Prevost H3-45",
        "year": 2023,
        "seating_capacity": TEST_DEFAULTS["SEATING_CAPACITY"],
        "dot_inspection_expiry": TEST_DEFAULTS["DOT_INSPECTION_EXPIRY"],
        "maintenance_due_miles": TEST_DEFAULTS["MAINTENANCE_DUE_MILES"],
        "insurance_policy_number": f"INS-{n:04d}",
        "insurance_expiry": TEST_DEFAULTS["INSURANCE_EXPIRY"],
    }
    defaults.update(overrides)
    return defaults


def create_driver_payload(**overrides) -> dict:
    n = next(_cdl_counter)
    defaults = {
        "full_name": f"Test Driver {n}",
        "cdl_number": f"CDL-{n:04d}",
        "cdl_class": "CLASS_B",
        "endorsements": ["P"],
        "hire_date": "2020-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "trip_date": TEST_DEFAULTS["TRIP_DATE"],
        "return_date": TEST_DEFAULTS["RETURN_DATE"],
        "origin": "Dallas TX",
        "destination": "Austin TX",
        "passenger_count": TEST_DEFAULTS["PASSENGER_COUNT"],
        "estimated_miles": TEST_DEFAULTS["ESTIMATED_MILES"],
        "estimated_hours": TEST_DEFAULTS["ESTIMATED_HOURS"],
        "vehicle_class_requested": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_trip_log_payload(driver_id: str, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "log_type": "DRIVING",
        "start_time": "2026-07-10T08:00:00Z",
        "end_time": "2026-07-10T12:00:00Z",
        "start_location": "Dallas TX",
        "end_location": "Austin TX",
        "miles_driven": 200,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(driver_id: str, vehicle_id: str, **overrides) -> dict:
    defaults = {
        "driver_id": driver_id,
        "vehicle_id": vehicle_id,
        "incident_type": "ACCIDENT",
        "severity": "MINOR",
        "description": "Minor fender bender in parking lot",
        "occurred_at": "2026-07-10T14:00:00Z",
        "reported_by": "Test Driver",
    }
    defaults.update(overrides)
    return defaults


def create_maintenance_record_payload(**overrides) -> dict:
    defaults = {
        "maintenance_type": "PREVENTIVE",
        "scheduled_date": "2026-08-01T00:00:00Z",
        "description": "Scheduled preventive service",
        "technician": "Tech A",
        "cost_cents": 50000,
        "odometer_at_service": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_breakdown_payload(vehicle_id: str, driver_id: str, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "driver_id": driver_id,
        "location": "I-35 Mile 100",
        "description": "Engine overheating",
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(order_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "venue_name": "Convention Center",
        "venue_address": "1000 Convention Blvd",
        "certificate_type": "GENERAL_LIABILITY",
        "coverage_amount_cents": 100000000,
    }
    defaults.update(overrides)
    return defaults


def create_safety_audit_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "audit_type": "DOT_COMPLIANCE",
        "requested_date": "2026-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
