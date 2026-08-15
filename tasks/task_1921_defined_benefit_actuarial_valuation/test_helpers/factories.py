"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "sponsor_name": "Test Sponsor Co",
        "plan_year": TEST_DEFAULTS["PLAN_YEAR"],
        "accrual_rate": TEST_DEFAULTS["ACCRUAL_RATE"],
        "normal_retirement_age": TEST_DEFAULTS["NORMAL_RETIREMENT_AGE"],
        "prior_aftap_pct": TEST_DEFAULTS["PRIOR_AFTAP_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_actuary_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Actuary",
        "credential_id": "EA-000",
        "enrollment_status": "ENROLLED",
    }
    defaults.update(overrides)
    return defaults


def create_census_batch_payload(**overrides) -> dict:
    defaults = {
        "plan_year": TEST_DEFAULTS["PLAN_YEAR"],
        "source_label": "census-1",
    }
    defaults.update(overrides)
    return defaults


def create_participant_row(**overrides) -> dict:
    """A single participant row for the bulk-append payload."""
    defaults = {
        "external_ref": "P1",
        "date_of_birth": "1965-01-01",
        "status": "RETIREE",
        "current_annual_benefit": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_participants_payload(rows) -> dict:
    return {"participants": rows}


def create_assumption_set_payload(**overrides) -> dict:
    defaults = {
        "plan_year": TEST_DEFAULTS["PLAN_YEAR"],
        "label": "base",
        "mortality_table": TEST_DEFAULTS["MORTALITY_TABLE"],
        "funding_discount_rate": TEST_DEFAULTS["FUNDING_DISCOUNT_RATE"],
        "disclosure_discount_rate": TEST_DEFAULTS["DISCLOSURE_DISCOUNT_RATE"],
        "retirement_age": TEST_DEFAULTS["NORMAL_RETIREMENT_AGE"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_statement_payload(**overrides) -> dict:
    defaults = {
        "plan_year": TEST_DEFAULTS["PLAN_YEAR"],
        "market_value_begin": 1000,
        "contributions_received": 0,
        "benefits_paid": 50,
        "investment_return": 50,
    }
    defaults.update(overrides)
    return defaults


def create_asset_valuation_payload(**overrides) -> dict:
    defaults = {
        "plan_year": TEST_DEFAULTS["PLAN_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_valuation_run_payload(**overrides) -> dict:
    defaults = {
        "plan_year": TEST_DEFAULTS["PLAN_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_credit_balance_election_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults


def create_contribution_payment_payload(**overrides) -> dict:
    defaults = {
        "amount": 100.00,
        "paid_on": "2028-05-01",
    }
    defaults.update(overrides)
    return defaults


def create_pbgc_filing_payload(**overrides) -> dict:
    defaults = {
        "premium_method": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_report_payload(**overrides) -> dict:
    defaults = {}
    defaults.update(overrides)
    return defaults
