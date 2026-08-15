"""Payload factories — one per creatable resource, input fields only.

Defaults follow the PRD narratives; callers override whatever a test needs
to control (hire dates for tenure, windows for criteria, fees for claims).
"""
from .constants import TEST_DEFAULTS


def create_nurse_payload(**overrides) -> dict:
    defaults = {
        "employee_code": "RN-1000",
        "full_name": "Test Nurse",
        "hire_date": TEST_DEFAULTS["HIRE_DATE"],
        "home_unit": TEST_DEFAULTS["HOME_UNIT"],
    }
    defaults.update(overrides)
    return defaults


def create_ladder_criterion_payload(**overrides) -> dict:
    defaults = {
        "target_level": "CN_II",
        "min_portfolio_score": TEST_DEFAULTS["MIN_PORTFOLIO_SCORE"],
        "min_participation_points": 0,
        "required_certification_track": "NONE",
        "differential_monthly_cents": TEST_DEFAULTS["DIFFERENTIAL_CN_II_CENTS"],
        "effective_from": TEST_DEFAULTS["CRITERION_EFFECTIVE_FROM"],
        "effective_until": None,
    }
    defaults.update(overrides)
    return defaults


def create_participation_event_payload(**overrides) -> dict:
    defaults = {
        "nurse_id": "",
        "event_kind": "QI_PROJECT",
        "points": 5,
        "occurred_on": "2026-01-15T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "nurse_id": "",
        "track": "BASIC",
        "certifying_body": "ANCC",
        "exam_fee_cents": TEST_DEFAULTS["EXAM_FEE_CENTS"],
        "obtained_on": "2026-01-01T00:00:00Z",
        "expires_on": "2031-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_reimbursement_claim_payload(**overrides) -> dict:
    defaults = {
        "certification_id": "",
        "claimed_amount_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    defaults = {
        "nurse_id": "",
        "target_level": "CN_II",
        "portfolio_narrative": "portfolio narrative",
        "expected_nurse_version": 1,
    }
    defaults.update(overrides)
    return defaults


def create_review_assignment_payload(**overrides) -> dict:
    defaults = {"reviewer_nurse_id": ""}
    defaults.update(overrides)
    return defaults


def score_payload(value: int = 80, **overrides) -> dict:
    """All four committee dimensions at the same value (PRD §3.4)."""
    dims = {
        "leadership": value,
        "clinical_expertise": value,
        "professional_development": value,
        "outcomes": value,
    }
    dims.update(overrides)
    return {"dimension_scores": dims}


def create_anniversary_review_payload(**overrides) -> dict:
    defaults = {"nurse_id": "", "review_year": 2026}
    defaults.update(overrides)
    return defaults


def close_review_payload(**overrides) -> dict:
    defaults = {"outcome": "SUSTAIN"}
    defaults.update(overrides)
    return defaults


def decide_payload(outcome="APPROVE", expected_application_version=1, **overrides) -> dict:
    defaults = {
        "outcome": outcome,
        "expected_application_version": expected_application_version,
    }
    defaults.update(overrides)
    return defaults


def create_budget_line_payload(**overrides) -> dict:
    defaults = {
        "unit": TEST_DEFAULTS["HOME_UNIT"],
        "fiscal_year": 2027,
        "allocated_cents": TEST_DEFAULTS["BUDGET_ALLOCATED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def update_budget_line_payload(**overrides) -> dict:
    defaults = {
        "allocated_cents": TEST_DEFAULTS["BUDGET_ALLOCATED_CENTS"],
        "expected_budget_line_version": 1,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str = "2026-08-01T00:00:00Z") -> dict:
    return {"to_iso8601": to_iso8601}
