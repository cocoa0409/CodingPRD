"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import (
    CANONICAL_PROFILE_PAYLOAD,
    CANONICAL_START_DATE,
    CANONICAL_BASE_SALARY_CENTS,
    CANONICAL_SIGNING_BONUS_CENTS,
    CANONICAL_RELOCATION_CENTS,
)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_role_profile_payload(**overrides) -> dict:
    defaults = dict(CANONICAL_PROFILE_PAYLOAD)
    defaults["name"] = _uniq("SE")
    defaults.update(overrides)
    return defaults


def create_employee_payload(**overrides) -> dict:
    defaults = {
        "full_name": _uniq("Employee"),
        "email": f"{_uniq('emp')}@x.com",
    }
    defaults.update(overrides)
    return defaults


def create_new_hire_payload(**overrides) -> dict:
    defaults = {
        "full_name": _uniq("NewHire"),
        "personal_email": f"{_uniq('nh')}@x.com",
        "start_date": CANONICAL_START_DATE,
        "department": "Engineering",
    }
    defaults.update(overrides)
    return defaults


def create_onboarding_case_payload(**overrides) -> dict:
    defaults = {
        "start_date": CANONICAL_START_DATE,
        "base_salary_cents": CANONICAL_BASE_SALARY_CENTS,
        "signing_bonus_cents": CANONICAL_SIGNING_BONUS_CENTS,
        "relocation_stipend_cents": CANONICAL_RELOCATION_CENTS,
        "benefits_tier": "PLUS",
    }
    defaults.update(overrides)
    return defaults


def create_orientation_session_payload(**overrides) -> dict:
    defaults = {
        "room": _uniq("R"),
        "starts_at": "2026-05-04T09:00:00Z",
        "ends_at": "2026-05-04T12:00:00Z",
        "capacity": 10,
    }
    defaults.update(overrides)
    return defaults


def create_payroll_handoff_payload(**overrides) -> dict:
    defaults = {
        "first_period_start_date": "2026-05-01",
        "first_period_end_date": "2026-05-14",
    }
    defaults.update(overrides)
    return defaults
