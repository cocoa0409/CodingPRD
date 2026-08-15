"""Payload factories — one per creatable resource, input fields only (PRD §3).

Uniqueness-sensitive fields (nurse email, license number, requirement code, unit
name) default to uuid-suffixed values so composite fixtures can create many
resources inside one test without tripping the duplicate-resource rule.
"""
from uuid import uuid4

from .constants import TEST_DEFAULTS


def _tag() -> str:
    return uuid4().hex[:8]


def create_nurse_payload(**overrides) -> dict:
    tag = _tag()
    defaults = {
        "full_name": f"Test Nurse {tag}",
        "email": f"nurse.{tag}@x.com",
        "primary_state_of_residence": TEST_DEFAULTS["NURSE_PSOR"],
        "employment_type": TEST_DEFAULTS["NURSE_EMPLOYMENT_TYPE"],
        "hire_date": TEST_DEFAULTS["NURSE_HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_state_license_payload(nurse_id, **overrides) -> dict:
    tag = _tag()
    defaults = {
        "nurse_id": nurse_id,
        "state_code": TEST_DEFAULTS["LICENSE_STATE"],
        "license_number": f"RN-AZ-{tag}",
        "license_class": TEST_DEFAULTS["LICENSE_CLASS"],
        "multistate_flag": True,
        "issued_on": TEST_DEFAULTS["LICENSE_ISSUED_ON"],
        "expires_on": TEST_DEFAULTS["LICENSE_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_psv_payload(license_id, **overrides) -> dict:
    defaults = {"license_id": license_id, "channel": "NURSYS"}
    defaults.update(overrides)
    return defaults


def create_certification_payload(nurse_id, **overrides) -> dict:
    defaults = {
        "nurse_id": nurse_id,
        "cert_type": "BLS",
        "issuing_body": TEST_DEFAULTS["CERT_ISSUING_BODY"],
        "obtained_on": "2026-05-01",
        "expires_on": TEST_DEFAULTS["BLS_EXPIRES_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_disciplinary_action_payload(nurse_id, **overrides) -> dict:
    defaults = {
        "nurse_id": nurse_id,
        "scope": "PRIVILEGE",
        "action_type": "REPRIMAND",
        "effective_on": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_credential_packet_payload(nurse_id, target_unit_id, **overrides) -> dict:
    defaults = {"nurse_id": nurse_id, "target_unit_id": target_unit_id}
    defaults.update(overrides)
    return defaults


def create_competency_requirement_payload(**overrides) -> dict:
    tag = _tag()
    defaults = {
        "code": f"ANNUAL_SKILLS_{tag}",
        "name": "Annual Skills",
        "validity_months": 12,
        "window_mode": "ROLLING",
        "mandatory": True,
        "applies_to": ["STAFF", "TRAVEL", "PER_DIEM"],
    }
    defaults.update(overrides)
    return defaults


def create_competency_completion_payload(nurse_id, requirement_id, **overrides) -> dict:
    defaults = {
        "nurse_id": nurse_id,
        "requirement_id": requirement_id,
        "completed_on": TEST_DEFAULTS["COMPLETED_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    tag = _tag()
    defaults = {"name": f"UNIT-{tag}", "required_cert_types": []}
    defaults.update(overrides)
    return defaults


def create_shift_assignment_payload(nurse_id, unit_id, starts_at, ends_at, **overrides) -> dict:
    defaults = {
        "nurse_id": nurse_id,
        "unit_id": unit_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    defaults.update(overrides)
    return defaults


def create_competency_session_payload(requirement_id, **overrides) -> dict:
    tag = _tag()
    defaults = {
        "requirement_id": requirement_id,
        "title": f"Session {tag}",
        "starts_at": "2026-08-05T09:00:00Z",
        "ends_at": "2026-08-05T12:00:00Z",
        "capacity": 2,
    }
    defaults.update(overrides)
    return defaults


def create_audit_run_payload(**overrides) -> dict:
    defaults = {
        "window_start": "2026-07-01",
        "window_end": "2026-08-01",
        "per_unit_sample_size": 5,
    }
    defaults.update(overrides)
    return defaults
