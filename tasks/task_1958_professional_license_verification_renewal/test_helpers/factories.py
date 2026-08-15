"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import PE_TYPE_PAYLOAD, RN_TYPE_PAYLOAD

_email_counter = itertools.count(1)
_license_number_counter = itertools.count(1000)


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}.{next(_email_counter)}@example.com"


def _unique_license_number(prefix: str = "LIC") -> str:
    return f"{prefix}-{next(_license_number_counter)}"


def create_license_type_payload(**overrides) -> dict:
    """Defaults mirror the RN RECEIPT_BASED policy used across the suite."""
    defaults = dict(RN_TYPE_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_pe_license_type_payload(**overrides) -> dict:
    """Defaults mirror the PE FLAT_SCHEDULE policy used across the suite."""
    defaults = dict(PE_TYPE_PAYLOAD)
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Nora Nurse",
        "work_email": _unique_email("employee"),
        "role_code": "STAFF_NURSE",
    }
    defaults.update(overrides)
    return defaults


def create_role_requirement_payload(**overrides) -> dict:
    defaults = {
        "role_code": "STAFF_NURSE",
        "license_type_id": "",  # caller must supply
        "state_code": "CA",
        "is_required": True,
    }
    defaults.update(overrides)
    return defaults


def create_license_payload(**overrides) -> dict:
    defaults = {
        "employee_id": "",  # caller must supply
        "license_type_id": "",  # caller must supply
        "state_code": "CA",
        "license_number": _unique_license_number(),
        "issued_on": "2026-01-01",
        "expires_on": "2027-06-30",
    }
    defaults.update(overrides)
    return defaults


def create_verification_payload(**overrides) -> dict:
    defaults = {
        "verified_on": "2026-08-01",
        "source": "STATE_BOARD_API",
        "outcome": "VERIFIED",
    }
    defaults.update(overrides)
    return defaults


def create_ce_activity_payload(**overrides) -> dict:
    defaults = {
        "provider_name": "CEU Inc",
        "activity_title": "Refresher Course",
        "hours": 10.0,
        "completed_on": "2026-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_renewal_request_payload(**overrides) -> dict:
    defaults = {
        "claimed_amount_cents": 50_000,
        "expected_license_version": 1,  # caller should re-read the live version
    }
    defaults.update(overrides)
    return defaults


def create_disciplinary_event_payload(**overrides) -> dict:
    defaults = {
        "board_case_number": f"B-{next(_license_number_counter)}",
        "event_type": "WARNING",
        "effective_on": "2026-08-01",
        "received_via": "BOARD_FEED",
    }
    defaults.update(overrides)
    return defaults


def create_exclusion_screening_payload(**overrides) -> dict:
    defaults = {
        "list_source": "OIG_LEIE",
        "screened_on": "2026-08-01",
        "outcome": "CLEAR",
    }
    defaults.update(overrides)
    return defaults


def create_audit_package_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2026-08-01",
        "period_end": "2026-09-01",
    }
    defaults.update(overrides)
    return defaults
