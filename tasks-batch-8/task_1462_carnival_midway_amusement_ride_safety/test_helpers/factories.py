"""Payload factories — one per entity, input fields only (PRD sections 3.1-3.8)."""
from .constants import CERT_FAR_FUTURE, SEASON

FAIR_DATES = dict(SEASON)


def create_fair_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Midway",
        "operator_company_name": "ShowCo",
        "location": "Lot 1",
        "setup_start_date": SEASON["setup_start_date"],
        "opening_date": SEASON["opening_date"],
        "closing_date": SEASON["closing_date"],
        "teardown_end_date": SEASON["teardown_end_date"],
        "midway_capacity": 300,
    }
    defaults.update(overrides)
    return defaults


def create_ride_payload(fair_id: str, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "name": "Coaster",
        "manufacturer": "MFG",
        "model": "X1",
        "serial_number": "SN-1",
        "ride_class": "THRILL",
        "capacity_per_cycle": 4,
        "min_rider_height_in": 48,
        "max_rider_height_in": 80,
        "wind_limit_mph": 30,
        "cycle_inspection_interval": 5,
        "annual_cert_expires_on": CERT_FAR_FUTURE,
    }
    defaults.update(overrides)
    return defaults


def create_inspector_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Inspector One",
        "license_number": "LIC-1",
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(fair_id: str, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "scope": "FAIR_WIDE",
        "scheduled_date": "2026-08-02",
        "start_hour": 9,
        "duration_hours": 2,
    }
    defaults.update(overrides)
    return defaults


def create_staff_payload(fair_id: str, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "full_name": "Staff One",
        "functions": ["SUPERVISOR"],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(staff_id: str, **overrides) -> dict:
    defaults = {
        "staff_id": staff_id,
        "ride_class": "THRILL",
        "issued_on": "2026-08-01",
        "expires_on": CERT_FAR_FUTURE,
    }
    defaults.update(overrides)
    return defaults


def create_operating_day_payload(fair_id: str, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "date": "2026-08-03",
        "max_attendance": 100,
    }
    defaults.update(overrides)
    return defaults


def create_checklist_payload(ride_id: str, day_id: str, **overrides) -> dict:
    defaults = {
        "ride_id": ride_id,
        "operating_day_id": day_id,
        "items_total": 5,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(ride_id: str, day_id: str, **overrides) -> dict:
    defaults = {
        "ride_id": ride_id,
        "operating_day_id": day_id,
    }
    defaults.update(overrides)
    return defaults


def create_redemption_payload(wristband_id: str, ride_id: str, **overrides) -> dict:
    defaults = {
        "wristband_id": wristband_id,
        "ride_id": ride_id,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(fair_id: str, **overrides) -> dict:
    defaults = {
        "fair_id": fair_id,
        "name": "Credits",
        "kind": "CREDIT_BUNDLE",
        "base_price_cents": 100,
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(product_id: str, day_id: str, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "operating_day_id": day_id,
        "quantity": 1,
        "holder_height_in": 60,
    }
    defaults.update(overrides)
    return defaults


def create_observation_payload(day_id: str, **overrides) -> dict:
    defaults = {
        "operating_day_id": day_id,
        "wind_speed_mph": 10,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(ride_id: str, day_id: str, **overrides) -> dict:
    defaults = {
        "ride_id": ride_id,
        "operating_day_id": day_id,
        "severity": "MINOR",
        "injury_count": 0,
        "description": "incident report",
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(staff_id: str, expected_staff_version: int, **overrides) -> dict:
    defaults = {
        "staff_id": staff_id,
        "work_date": "2026-08-01",
        "start_hour": 6,
        "end_hour": 10,
        "shift_role": "SETUP",
        "expected_staff_version": expected_staff_version,
    }
    defaults.update(overrides)
    return defaults
