"""Payload factories — one per entity, input fields only.

Each factory returns a fresh dict of the input fields the corresponding create
endpoint accepts. Callers override any field via keyword arguments.
"""
import itertools

_email_counter = itertools.count(1)
_license_counter = itertools.count(1)


def unique_email(prefix: str = "clinician") -> str:
    """A process-unique email so Clinician.email uniqueness never collides."""
    return f"{prefix}.{next(_email_counter)}@example.com"


def unique_license(prefix: str = "LIC") -> str:
    return f"{prefix}-{next(_license_counter)}"


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Facility",
        "unit_name": "ICU",
        "unit_capacity": 2,
        "required_credential_types": ["RN_LICENSE"],
    }
    defaults.update(overrides)
    return defaults


def create_clinician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Clinician",
        "email": unique_email(),
        "specialty": "RN",
    }
    defaults.update(overrides)
    return defaults


def create_credential_payload(**overrides) -> dict:
    defaults = {
        "credential_type": "RN_LICENSE",
        "license_number": unique_license("RN"),
        "issued_on": "2025-01-01T00:00:00Z",
        "expires_on": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    defaults = {
        "specialty": "RN",
        "base_pay_rate_cents_per_hour": 7500,
        "effective_from": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(facility_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "specialty": "RN",
        "headcount": 1,
        "urgency": "STANDARD",
        "window_start": "2026-06-08T00:00:00Z",
        "window_end": "2026-06-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_shift_payload(**overrides) -> dict:
    defaults = {
        "scheduled_start": "2026-06-08T07:00:00Z",
        "scheduled_end": "2026-06-08T19:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(clinician_id, **overrides) -> dict:
    defaults = {"clinician_id": clinician_id}
    defaults.update(overrides)
    return defaults


def submit_timesheet_payload(**overrides) -> dict:
    defaults = {
        "clock_in": "2026-06-08T07:00:00Z",
        "clock_out": "2026-06-08T19:00:00Z",
        "break_minutes": 30,
    }
    defaults.update(overrides)
    return defaults


def create_invoice_payload(facility_id, expected_facility_version, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "period_start": "2026-06-08T00:00:00Z",
        "period_end": "2026-06-15T00:00:00Z",
        "expected_facility_version": expected_facility_version,
    }
    defaults.update(overrides)
    return defaults
