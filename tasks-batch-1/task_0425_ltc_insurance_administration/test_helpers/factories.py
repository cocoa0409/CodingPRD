"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Optional fields (those the PRD marks optional or
with a server-side default) are omitted unless explicitly overridden.
"""
from .constants import TEST_DEFAULTS


def create_policyholder_payload(**overrides) -> dict:
    """Required: full_name, state_code, date_of_birth. Optional: medicaid_state_eligible."""
    defaults = {
        "full_name": "Test Insured",
        "state_code": "CA",
        "date_of_birth": "1950-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(policyholder_id: str, **overrides) -> dict:
    """Required: policyholder_id, product_mode, daily_benefit_max_cents,
    monthly_benefit_max_cents, initial_pool_cents, inflation_rider,
    elimination_period_days. Optional: is_partnership_policy."""
    defaults = {
        "policyholder_id": policyholder_id,
        "product_mode": "REIMBURSEMENT",
        "daily_benefit_max_cents": TEST_DEFAULTS["DAILY_BENEFIT_MAX_CENTS"],
        "monthly_benefit_max_cents": TEST_DEFAULTS["MONTHLY_BENEFIT_MAX_CENTS"],
        "initial_pool_cents": TEST_DEFAULTS["INITIAL_POOL_CENTS"],
        "inflation_rider": "NONE",
        "elimination_period_days": 0,
    }
    defaults.update(overrides)
    return defaults


def create_premium_invoice_payload(period_index: int, **overrides) -> dict:
    """Required: period_index, base_premium_cents, due_date, grace_deadline."""
    defaults = {
        "period_index": period_index,
        "base_premium_cents": TEST_DEFAULTS["BASE_PREMIUM_CENTS"],
        "due_date": TEST_DEFAULTS["DUE_DATE"],
        "grace_deadline": TEST_DEFAULTS["GRACE_DEADLINE"],
    }
    defaults.update(overrides)
    return defaults


def create_rate_filing_payload(policy_id: str, **overrides) -> dict:
    """Required: policy_id, requested_increase_pct, effective_period_index."""
    defaults = {
        "policy_id": policy_id,
        "requested_increase_pct": 40,
        "effective_period_index": 1,
    }
    defaults.update(overrides)
    return defaults


def create_trigger_certification_payload(**overrides) -> dict:
    """Required: adl_deficiencies. Optional: cognitive_impairment, supersedes_id."""
    defaults = {
        "adl_deficiencies": ["BATHING", "DRESSING"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    """Required: name, provider_type, state_code. Optional: license_active."""
    defaults = {
        "name": "Test Provider",
        "provider_type": "NURSING_HOME",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_care_plan_payload(policy_id: str, provider_id: str, **overrides) -> dict:
    """Required: policy_id, provider_id, care_setting."""
    defaults = {
        "policy_id": policy_id,
        "provider_id": provider_id,
        "care_setting": "NURSING_HOME",
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id: str, care_plan_id: str, expected_policy_version: int, **overrides) -> dict:
    """Required: policy_id, care_plan_id, service_month, expected_policy_version."""
    defaults = {
        "policy_id": policy_id,
        "care_plan_id": care_plan_id,
        "service_month": "2026-03",
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(service_date: str, billed_charge_cents: int, **overrides) -> dict:
    """Required: service_date, billed_charge_cents. Optional: is_qualifying_day."""
    defaults = {
        "service_date": service_date,
        "billed_charge_cents": billed_charge_cents,
    }
    defaults.update(overrides)
    return defaults


def adjudicate_payload(granted_pct: int, expected_policy_version: int, **overrides) -> dict:
    """Required: granted_pct, expected_policy_version."""
    defaults = {
        "granted_pct": granted_pct,
        "expected_policy_version": expected_policy_version,
    }
    defaults.update(overrides)
    return defaults


def advance_clock_payload(to_iso8601: str) -> dict:
    """Required: to_iso8601."""
    return {"to_iso8601": to_iso8601}
