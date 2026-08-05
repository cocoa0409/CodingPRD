"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS

_account_seq = [0]


def unique_account_number(prefix="ACC"):
    _account_seq[0] += 1
    return f"{prefix}-{_account_seq[0]}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Acme LLC",
        "email": "c@acme.co",
        "segment": "SMALL_COMMERCIAL",
        "service_state": "TX",
    }
    defaults.update(overrides)
    return defaults


def create_broker_user_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Agent A",
        "email": "a@brk.co",
        "staff_role": "AGENT",
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "name": "PowerCo",
        "commodity": "ELECTRICITY",
        "service_states": ["TX"],
    }
    defaults.update(overrides)
    return defaults


def create_account_payload(customer_id, broker_agent_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "broker_agent_id": broker_agent_id,
        "utility_name": "Oncor",
        "account_number": overrides.pop("account_number", unique_account_number()),
        "commodity": "ELECTRICITY",
        "state_code": "TX",
        "estimated_annual_usage_kwh": TEST_DEFAULTS["ESTIMATED_ANNUAL_USAGE_KWH"],
    }
    defaults.update(overrides)
    return defaults


def create_authorization_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "scope": "USAGE_AND_ENROLL",
        "expires_at": TEST_DEFAULTS["LOA_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_usage_record_payload(account_id, period_month, usage_kwh, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "period_month": period_month,
        "usage_kwh": usage_kwh,
    }
    defaults.update(overrides)
    return defaults


def create_rfp_payload(account_id, broker_agent_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "broker_agent_id": broker_agent_id,
        "term_months_requested": TEST_DEFAULTS["TERM_MONTHS"],
        "due_at": TEST_DEFAULTS["RFP_DUE_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(rfp_id, supplier_id, expected_rfp_version, **overrides) -> dict:
    defaults = {
        "rfp_id": rfp_id,
        "supplier_id": supplier_id,
        "rate_mills_per_kwh": TEST_DEFAULTS["RATE_MILLS_PER_KWH"],
        "term_months": TEST_DEFAULTS["TERM_MONTHS"],
        "broker_adder_mills": TEST_DEFAULTS["BROKER_ADDER_MILLS"],
        "expected_rfp_version": expected_rfp_version,
    }
    defaults.update(overrides)
    return defaults


def award_contract_payload(rfp_id, account_id, **overrides) -> dict:
    defaults = {
        "rfp_id": rfp_id,
        "account_id": account_id,
        "estimated_annual_usage_kwh": TEST_DEFAULTS["ESTIMATED_ANNUAL_USAGE_KWH"],
        "start_date": TEST_DEFAULTS["START_DATE"],
        "requested_switch_date": TEST_DEFAULTS["START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_dr_enrollment_payload(account_id, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "program_name": "Summer DR",
        "season_start": "2026-08-01T00:00:00Z",
        "season_end": "2026-09-30T00:00:00Z",
        "committed_kw": 100,
        "incentive_per_kw_cents": 4500,
    }
    defaults.update(overrides)
    return defaults
