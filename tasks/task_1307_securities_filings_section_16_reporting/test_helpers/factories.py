"""Payload factories — one per entity, input fields only (PRD §3/§4)."""
from .constants import TEST_DEFAULTS


def create_issuer_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["ISSUER_NAME"],
        "ticker": TEST_DEFAULTS["TICKER"],
        "cik": TEST_DEFAULTS["CIK"],
        "shares_outstanding": TEST_DEFAULTS["SHARES_OUTSTANDING"],
        "fiscal_year_end_month": TEST_DEFAULTS["FISCAL_YEAR_END_MONTH"],
        "edgar_ccc": TEST_DEFAULTS["EDGAR_CCC"],
    }
    defaults.update(overrides)
    return defaults


def create_reporting_person_payload(**overrides) -> dict:
    defaults = {
        "issuer_id": "",
        "full_name": TEST_DEFAULTS["PERSON_NAME"],
        "person_cik": TEST_DEFAULTS["PERSON_CIK"],
    }
    defaults.update(overrides)
    return defaults


def create_transaction_payload(**overrides) -> dict:
    defaults = {
        "reporting_person_id": "",
        "transaction_date": "2026-08-01",
        "transaction_code": "P",
        "security_type": "COMMON_STOCK",
        "shares": 100,
        "price_per_share": 10.00,
    }
    defaults.update(overrides)
    return defaults


def create_filing_payload(**overrides) -> dict:
    defaults = {
        "issuer_id": "",
        "reporting_person_id": "",
        "form_type": "FORM_3",
    }
    defaults.update(overrides)
    return defaults


def create_trading_plan_payload(**overrides) -> dict:
    defaults = {
        "reporting_person_id": "",
        "plan_name": "Plan A",
        "first_trade_date": "2026-09-01",
        "expiration_date": "2027-03-01",
    }
    defaults.update(overrides)
    return defaults


def create_blackout_window_payload(**overrides) -> dict:
    defaults = {
        "issuer_id": "",
        "start_date": "2026-09-28",
        "end_date": "2026-10-02",
        "reason": "quarterly earnings blackout",
    }
    defaults.update(overrides)
    return defaults


def create_beneficial_holder_payload(**overrides) -> dict:
    defaults = {
        "issuer_id": "",
        "holder_name": TEST_DEFAULTS["HOLDER_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_position_change_payload(**overrides) -> dict:
    defaults = {
        "shares_delta": 10000,
        "derivative_shares_delta": 0,
        "effective_date": "2026-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_annual_sweep_payload(**overrides) -> dict:
    defaults = {
        "issuer_id": "",
        "fiscal_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_filing_agent_authorization_payload(**overrides) -> dict:
    defaults = {
        "issuer_id": "",
        "agent_user_id": TEST_DEFAULTS["FILING_AGENT_ID"],
    }
    defaults.update(overrides)
    return defaults
