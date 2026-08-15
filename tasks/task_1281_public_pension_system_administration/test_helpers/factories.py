"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "FUND_NAME": "State Retirement",
    "COLA_RATE_PCT": 0.025,
    "EARNINGS_LIMIT_ANNUAL_CENTS": 3_000_000,
    "EMPLOYER_NAME": "City Hall",
    "EMPLOYER_CODE": "CH",
    "MEMBER_FULL_NAME": "Member One",
    "MEMBER_DOB": "1966-01-01",
    "MEMBER_HIRE_DATE": "2016-01-01",
    "PURCHASE_TYPE": "MILITARY",
    "PURCHASE_PERIOD_START": "2005-01-01",
    "PURCHASE_PERIOD_END": "2006-12-31",
    "YEARS_PURCHASED": 2.0,
    "OPTION_ELECTION": "SINGLE_LIFE",
    "DISABILITY_TYPE": "DUTY",
    "BENEFICIARY_FULL_NAME": "Spouse Sam",
    "BENEFICIARY_RELATIONSHIP": "spouse",
    "BENEFICIARY_DOB": "1968-01-01",
}


def create_pension_fund_payload(**overrides) -> dict:
    defaults = {
        "fund_name": DEFAULTS["FUND_NAME"],
        "cola_rate_pct": DEFAULTS["COLA_RATE_PCT"],
        "earnings_limit_annual_cents": DEFAULTS["EARNINGS_LIMIT_ANNUAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_employer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["EMPLOYER_NAME"],
        "employer_code": DEFAULTS["EMPLOYER_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(employer_id: str, **overrides) -> dict:
    defaults = {
        "employer_id": employer_id,
        "full_name": DEFAULTS["MEMBER_FULL_NAME"],
        "date_of_birth": DEFAULTS["MEMBER_DOB"],
        "hire_date": DEFAULTS["MEMBER_HIRE_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_contribution_report_payload(**overrides) -> dict:
    defaults = {
        "period_start": "2023-01-01",
        "period_end": "2024-01-01",
        "declared_total_cents": 480_000,
    }
    defaults.update(overrides)
    return defaults


def create_contribution_line_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "fiscal_year": 2023,
        "period_salary_cents": 6_000_000,
        "contribution_amount_cents": 480_000,
    }
    defaults.update(overrides)
    return defaults


def create_service_purchase_payload(**overrides) -> dict:
    defaults = {
        "purchase_type": DEFAULTS["PURCHASE_TYPE"],
        "service_period_start": DEFAULTS["PURCHASE_PERIOD_START"],
        "service_period_end": DEFAULTS["PURCHASE_PERIOD_END"],
        "years_purchased": DEFAULTS["YEARS_PURCHASED"],
    }
    defaults.update(overrides)
    return defaults


def create_retirement_application_payload(**overrides) -> dict:
    defaults = {"option_election": DEFAULTS["OPTION_ELECTION"]}
    defaults.update(overrides)
    return defaults


def create_disability_application_payload(**overrides) -> dict:
    defaults = {"disability_type": DEFAULTS["DISABILITY_TYPE"]}
    defaults.update(overrides)
    return defaults


def create_beneficiary_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["BENEFICIARY_FULL_NAME"],
        "relationship": DEFAULTS["BENEFICIARY_RELATIONSHIP"],
        "date_of_birth": DEFAULTS["BENEFICIARY_DOB"],
    }
    defaults.update(overrides)
    return defaults
