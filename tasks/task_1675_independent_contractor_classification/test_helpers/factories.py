"""Payload factories — input fields only, one per entity (PRD §3)."""
import itertools

from .constants import TEST_DEFAULTS

# The eight intake factor keys (PRD §3.3).
FACTOR_KEYS = [
    "CONTROL_METHOD",
    "CONTROL_HOURS",
    "OUTSIDE_USUAL_BUSINESS",
    "INDEPENDENT_TRADE",
    "PROFIT_LOSS",
    "INVESTMENT",
    "INTEGRAL_TO_BUSINESS",
    "PERMANENCY",
]

# Contractor-favorable answer for every factor under all three tests (PRD §3.1):
# CONTROL_METHOD/CONTROL_HOURS/INTEGRAL_TO_BUSINESS/PERMANENCY indicative at YES;
# PROFIT_LOSS/INVESTMENT indicative at NO; ABC prong B/C fail at NO for
# OUTSIDE_USUAL_BUSINESS/INDEPENDENT_TRADE.
FAVORABLE_ANSWERS = {
    "CONTROL_METHOD": "NO",
    "CONTROL_HOURS": "NO",
    "OUTSIDE_USUAL_BUSINESS": "YES",
    "INDEPENDENT_TRADE": "YES",
    "PROFIT_LOSS": "YES",
    "INVESTMENT": "YES",
    "INTEGRAL_TO_BUSINESS": "NO",
    "PERMANENCY": "NO",
}

_ein_counter = itertools.count(1)


def next_ein() -> str:
    """Unique EIN per call within a test process (ein must be unique, PRD §3.2)."""
    return f"12-{16750000 + next(_ein_counter):07d}"


def make_answers(**overrides) -> list:
    """All-8-factor answer set in canonical order; overrides flip named factors."""
    merged = dict(FAVORABLE_ANSWERS)
    merged.update(overrides)
    return [{"factor_key": k, "answer": merged[k]} for k in FACTOR_KEYS]


def create_jurisdiction_payload(**overrides) -> dict:
    defaults = {
        "code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "test_type": TEST_DEFAULTS["JURISDICTION_TEST_TYPE"],
        "employee_score_threshold": TEST_DEFAULTS["EMPLOYEE_SCORE_THRESHOLD"],
        "state_filing_threshold_cents": TEST_DEFAULTS["STATE_FILING_THRESHOLD_CENTS"],
        "max_active_exceptions": TEST_DEFAULTS["MAX_ACTIVE_EXCEPTIONS"],
        "min_insurance_cents": TEST_DEFAULTS["MIN_INSURANCE_CENTS"],
        "description": "Test jurisdiction",
    }
    defaults.update(overrides)
    return defaults


def create_contractor_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Test Contractor LLC",
        "entity_type": "LLC",
        "ein": next_ein(),
        "insurance_coverage_cents": TEST_DEFAULTS["CONTRACTOR_INSURANCE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(contractor_id: str, jurisdiction_id: str, **overrides) -> dict:
    defaults = {
        "contractor_id": contractor_id,
        "jurisdiction_id": jurisdiction_id,
        "title": "Test engagement",
        "scope_description": "Statement of work",
        "agreed_rate_cents": TEST_DEFAULTS["AGREED_RATE_CENTS"],
        "rate_unit": TEST_DEFAULTS["RATE_UNIT"],
        "start_date": TEST_DEFAULTS["ENGAGEMENT_START"],
        "end_date": TEST_DEFAULTS["ENGAGEMENT_END"],
        "supervision_level": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "start_date": TEST_DEFAULTS["CONTRACT_START"],
        "end_date": TEST_DEFAULTS["CONTRACT_END"],
        "rate_cents": TEST_DEFAULTS["AGREED_RATE_CENTS"],
        "rate_unit": TEST_DEFAULTS["RATE_UNIT"],
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(expected_contract_version: int, **overrides) -> dict:
    defaults = {
        "expected_contract_version": expected_contract_version,
        "scope_change_summary": "Scope adjustment",
    }
    defaults.update(overrides)
    return defaults


def create_exception_payload(**overrides) -> dict:
    defaults = {
        "justification": "Documented business justification for the classification risk",
        "expires_at": TEST_DEFAULTS["EXCEPTION_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_review_payload(scheduled_date: str = "2026-09-01") -> dict:
    return {"scheduled_date": scheduled_date}


def create_audit_payload(contractor_id: str, audit_type: str = "FIELDWORK", **overrides) -> dict:
    payload = {"contractor_id": contractor_id, "audit_type": audit_type}
    payload.update(overrides)
    return payload


def create_remediation_action_payload(**overrides) -> dict:
    defaults = {
        "description": "Remediation work item",
        "severity": "LOW",
        "due_date": "2026-09-30",
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(
    contractor_id: str,
    state_jurisdiction_id: str,
    tax_year: int = None,
    payment_line_items: list = None,
    **overrides,
) -> dict:
    payload = {
        "contractor_id": contractor_id,
        "state_jurisdiction_id": state_jurisdiction_id,
        "tax_year": tax_year if tax_year is not None else TEST_DEFAULTS["TAX_YEAR"],
        "payment_line_items": payment_line_items
        if payment_line_items is not None
        else [
            {"amount_cents": 80000, "payment_date": "2026-05-01", "kind": "SERVICE_FEE"}
        ],
    }
    payload.update(overrides)
    return payload


def create_inquiry_payload(**overrides) -> dict:
    defaults = {
        "agency_type": "STATE_EDD",
        "received_at": "2026-07-01T00:00:00Z",
        "response_deadline": "2026-09-01T00:00:00Z",
        "back_payments_cents": 2000000,
        "quarters_outstanding": 1,
    }
    defaults.update(overrides)
    return defaults


def create_conversion_payload(lookback_quarters: list = None, **overrides) -> dict:
    payload = {
        "lookback_quarters": lookback_quarters
        if lookback_quarters is not None
        else [
            {"quarter_label": "2025Q3", "service_fee_cents": 500000},
            {"quarter_label": "2025Q4", "service_fee_cents": 500000},
            {"quarter_label": "2026Q1", "service_fee_cents": 500000},
            {"quarter_label": "2026Q2", "service_fee_cents": 500000},
        ]
    }
    payload.update(overrides)
    return payload
