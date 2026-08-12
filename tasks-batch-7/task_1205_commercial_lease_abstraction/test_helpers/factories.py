"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_property_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["PROPERTY_NAME"],
        "address": TEST_DEFAULTS["PROPERTY_ADDRESS"],
        "total_rentable_sf": TEST_DEFAULTS["TOTAL_RENTABLE_SF"],
        "fiscal_year_end_month": TEST_DEFAULTS["FISCAL_YEAR_END_MONTH"],
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(**overrides) -> dict:
    defaults = {
        "tenant_legal_name": TEST_DEFAULTS["TENANT_LEGAL_NAME"],
        "suite": TEST_DEFAULTS["SUITE"],
        "leased_sf": TEST_DEFAULTS["LEASED_SF"],
        "commencement_date": TEST_DEFAULTS["COMMENCEMENT_DATE"],
        "expiration_date": TEST_DEFAULTS["EXPIRATION_DATE"],
        "base_rent_annual_cents": TEST_DEFAULTS["BASE_RENT_ANNUAL_CENTS"],
        "escalation_type": TEST_DEFAULTS["ESCALATION_TYPE"],
        "recovery_structure": TEST_DEFAULTS["RECOVERY_STRUCTURE"],
        "pro_rata_share_bps": TEST_DEFAULTS["PRO_RATA_SHARE_BPS"],
        "security_deposit_cents": TEST_DEFAULTS["SECURITY_DEPOSIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_rent_schedule_line_payload(**overrides) -> dict:
    defaults = {
        "period_start": TEST_DEFAULTS["SCHEDULE_PERIOD_START"],
        "period_end": TEST_DEFAULTS["SCHEDULE_PERIOD_END"],
        "base_rent_cents": TEST_DEFAULTS["SCHEDULE_BASE_RENT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_escalation_step_payload(**overrides) -> dict:
    defaults = {
        "step_index": 1,
        "kind": "FIXED_PCT",
        "pct_bps": 1000,
        "effective_on": "2027-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_recovery_pool_payload(**overrides) -> dict:
    defaults = {
        "category": TEST_DEFAULTS["POOL_CATEGORY"],
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "budgeted_cents": TEST_DEFAULTS["BUDGETED_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_recovery_billing_payload(**overrides) -> dict:
    defaults = {
        "pool_id": None,
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "period_index": 1,
    }
    defaults.update(overrides)
    return defaults


def create_reconciliation_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_critical_date_payload(**overrides) -> dict:
    defaults = {
        "kind": "NOTICE_DEADLINE",
        "due_date": "2027-06-30",
        "advance_notice_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_doc_payload(**overrides) -> dict:
    defaults = {
        "kind": "INSURANCE_CERT",
        "period_start": "2027-01-01",
        "period_end": "2028-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_amendment_payload(**overrides) -> dict:
    defaults = {
        "kind": "RENT_CHANGE",
        "effective_date": "2027-06-01",
    }
    defaults.update(overrides)
    return defaults


def create_tenant_challenge_payload(**overrides) -> dict:
    defaults = {
        "reconciliation_id": None,
        "reason_code": "MATH_ERROR",
        "claimed_overbilling_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_audit_right_payload(**overrides) -> dict:
    defaults = {
        "reconciliation_id": None,
        "invoked_on": "2027-04-01",
    }
    defaults.update(overrides)
    return defaults
