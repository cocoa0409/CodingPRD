"""Payload factories — one per creatable resource, input fields only.

Defaults follow the canonical fixtures used across the suite; every factory
accepts **overrides so tests can steer the values their claim cares about.
"""
from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_DEFAULT_ISO,
    TEST_DEFAULTS,
    V1_RATES,
)

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_fee_schedule_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "schedule_label": "FY2026 Adopted",
        "effective_date": CLOCK_DEFAULT_ISO,
        **V1_RATES,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "legal_name": f"DevCo {n}",
        "contact_email": f"dev{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_staff_reviewer_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "full_name": f"Reviewer {n}",
        "disciplines": ["PLANNING"],
    }
    defaults.update(overrides)
    return defaults


def create_decision_authority_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "full_name": f"Authority {n}",
        "body": "CITY_COUNCIL",
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(applicant_id: str, **overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "project_name": f"Project {n}",
        "applicant_id": applicant_id,
        "land_use_type": "RESIDENTIAL",
        "dwelling_units": TEST_DEFAULTS["DWELLING_UNITS"],
        "affordable_units": TEST_DEFAULTS["AFFORDABLE_UNITS"],
        "floor_area_sqft": TEST_DEFAULTS["FLOOR_AREA_SQFT"],
        "prior_use_basis": {},
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(
    project_id: str, expected_project_version: int, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "project_id": project_id,
        "application_type": "REZONE",
        "submittal_package": ["SITE_PLAN"],
        "expected_project_version": expected_project_version,
    }
    defaults.update(overrides)
    return defaults


def create_review_comment_payload(reviewer_id: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "reviewer_id": reviewer_id,
        "discipline": "PLANNING",
        "comment_text": "Review comment",
        "severity": "INFO",
    }
    defaults.update(overrides)
    return defaults


def create_outreach_event_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "event_date": "2026-08-03T00:00:00Z",
        "disposition": "OPPOSE",
        "attendee_count": TEST_DEFAULTS["ATTENDEE_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_hearing_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "hearing_date": "2026-08-25T00:00:00Z",
        "notice_posted_date": "2026-08-01T00:00:00Z",
        "hearing_body": "PLANNING_COMMISSION",
    }
    defaults.update(overrides)
    return defaults


def continue_hearing_payload(new_hearing_date: str, **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"new_hearing_date": new_hearing_date}
    defaults.update(overrides)
    return defaults


def renotice_hearing_payload(
    hearing_date: str, notice_posted_date: str, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "hearing_date": hearing_date,
        "notice_posted_date": notice_posted_date,
    }
    defaults.update(overrides)
    return defaults


def render_decision_payload(
    decided_by: str, expected_application_version: int, **overrides
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "decision": "APPROVE",
        "decided_by": decided_by,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def create_condition_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "condition_text": "Pay impact fees prior to permit issuance",
        "category": "FEE",
        "required_before": "PERMIT_ISSUANCE",
    }
    defaults.update(overrides)
    return defaults


def record_payment_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "amount": 1000.00,
        "paid_at": "2026-08-02T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_development_agreement_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "agreement_number": f"ORD-{n:04d}",
        "adoption_date": "2026-08-05T00:00:00Z",
        "vesting_term_years": TEST_DEFAULTS["VESTING_TERM_YEARS"],
        "registered_voters": TEST_DEFAULTS["REGISTERED_VOTERS"],
    }
    defaults.update(overrides)
    return defaults


def file_petition_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "filed_at": "2026-08-05T00:00:00Z",
        "valid_signature_count": 0,
    }
    defaults.update(overrides)
    return defaults


def file_appeal_payload(**overrides) -> Dict[str, Any]:
    n = _next()
    defaults: Dict[str, Any] = {
        "appellant_name": f"Appellant {n}",
        "filed_at": "2026-08-02T00:00:00Z",
        "grounds": "Procedural error",
    }
    defaults.update(overrides)
    return defaults


def request_permit_payload(**overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"permit_type": "GRADING"}
    defaults.update(overrides)
    return defaults


def resolve_appeal_payload(ruling: str = "UPHELD", **overrides) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {"ruling": ruling}
    defaults.update(overrides)
    return defaults
