"""Payload factories — input fields only (PRD §3, §4)."""
import itertools

from .constants import STD_MOD_DEFAULTS

_counter = itertools.count(1)


def _next() -> int:
    return next(_counter)


def create_borrower_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Test Borrower {n}",
        "email": f"borrower{n}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(borrower_id: str, **overrides) -> dict:
    n = _next()
    defaults = {
        "borrower_id": borrower_id,
        "loan_number": f"LN-{n:06d}",
        "property_state_code": "CA",
        "unpaid_principal_balance_cents": 20_000_000,
        "interest_rate_bp": 600,
        "remaining_term_months": 240,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(expected_loan_version: int, **overrides) -> dict:
    defaults = {
        "expected_loan_version": expected_loan_version,
        "hardship_type": "INCOME_REDUCTION",
        "stated_monthly_income_cents": 480_000,
    }
    defaults.update(overrides)
    return defaults


def create_document_payload(doc_type: str, **overrides) -> dict:
    defaults = {"doc_type": doc_type}
    defaults.update(overrides)
    return defaults


def create_program_option_payload(**overrides) -> dict:
    defaults = dict(STD_MOD_DEFAULTS)
    defaults.update(overrides)
    return defaults


def create_evaluation_payload(expected_application_version: int) -> dict:
    return {"expected_application_version": expected_application_version}


def create_payment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def create_modification_payload(trial_plan_id: str) -> dict:
    return {"trial_plan_id": trial_plan_id}


def create_appeal_payload(grounds: str = "please review") -> dict:
    return {"grounds": grounds}


def create_decision_payload(outcome: str) -> dict:
    return {"outcome": outcome}


def create_foreclosure_case_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "county": "Maricopa",
        "docket_number": f"FC-{n:06d}",
    }
    defaults.update(overrides)
    return defaults


def create_schedule_sale_payload(sale_date: str) -> dict:
    return {"sale_date": sale_date}


def create_escrow_analysis_payload(**overrides) -> dict:
    defaults = {
        "analysis_type": "STANDARD_ANNUAL",
        "comp_year_start_month": "2026-08",
        "comp_year_months": 12,
        "projected_annual_disbursements_cents": 420_000,
    }
    defaults.update(overrides)
    return defaults


def create_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
