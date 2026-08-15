"""Payload factories — one per entity, input fields only."""

from .constants import TEST_DEFAULTS


def create_staff_user_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Casey Counsel",
        "email": "casey@corp.example",
        "job_family": "LEGAL",
    }
    defaults.update(overrides)
    return defaults


def create_matter_payload(**overrides) -> dict:
    defaults = {
        "title": "Commercial dispute",
        "matter_type": "COMMERCIAL",
        "adverse_party": "Acme Corp",
        "jurisdiction": "N.D. Cal.",
        "filing_date": TEST_DEFAULTS["FILING_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_counsel_firm_payload(**overrides) -> dict:
    defaults = {
        "firm_name": "Outside LLP",
        "blended_rate_cap_cents": TEST_DEFAULTS["RATE_CAP_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_engagement_payload(**overrides) -> dict:
    defaults = {
        "role_type": "LEAD_COUNSEL",
        "fee_arrangement": "HOURLY",
        "proposed_rate_cents": TEST_DEFAULTS["PROPOSED_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_budget_payload(**overrides) -> dict:
    defaults = {
        "fiscal_year": TEST_DEFAULTS["FISCAL_YEAR"],
        "lifecycle_budget_cents": TEST_DEFAULTS["LIFECYCLE_BUDGET_CENTS"],
        "fy_budget_cents": TEST_DEFAULTS["FY_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_accrual_entry_payload(**overrides) -> dict:
    defaults = {
        "period": "2026-08",
        "entry_kind": "ACCRUAL",
        "amount_cents": 100_000,
    }
    defaults.update(overrides)
    return defaults


def create_hold_payload(**overrides) -> dict:
    defaults = {
        "scope_description": "All custodian email",
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "vendor_name": "DiscCo",
        "security_clearance_level": "RESTRICTED",
        "capacity_gb": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "service_type": "COLLECTION",
        "estimated_gb": 100,
        "rate_per_gb_cents": 1000,
        "scheduled_start": "2026-08-10T00:00:00Z",
        "scheduled_end": "2026-08-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_deadline_payload(**overrides) -> dict:
    defaults = {
        "deadline_type": "INTERNAL_REVIEW",
        "title": "Initial review",
        "due_at": TEST_DEFAULTS["DEADLINE_DUE"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(**overrides) -> dict:
    defaults = {
        "tier": "TIER_2",
        "approver_role": "GeneralCounsel",
        "max_single_amount_cents": 10_000_000,
        "dual_approval_required_over_cents": 50_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_request_payload(**overrides) -> dict:
    defaults = {
        "proposed_amount_cents": 5_000_000,
        "settlement_kind": "PAY_OUT",
        "terms_summary": "Full release",
        "expires_at": TEST_DEFAULTS["SETTLEMENT_EXPIRES_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_request_payload(**overrides) -> dict:
    defaults = {
        "payment_kind": "JUDGMENT",
        "amount_cents": 7_000_000,
        "payee_name": "Acme Corp",
    }
    defaults.update(overrides)
    return defaults
