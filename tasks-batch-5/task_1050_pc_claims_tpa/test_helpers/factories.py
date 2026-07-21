"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_client_account_payload(**overrides) -> dict:
    defaults = {
        "name": "Acme Carrier",
        "account_code": "ACCT-1",
        "reserve_authority_default_cents": TEST_DEFAULTS["RESERVE_AUTHORITY_DEFAULT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_policy_payload(client_account_id, **overrides) -> dict:
    defaults = {
        "client_account_id": client_account_id,
        "policy_number": "POL-1",
        "coverage_limit_cents": TEST_DEFAULTS["COVERAGE_LIMIT_CENTS"],
        "deductible_cents": 0,
        "per_claim_expense_limit_cents": TEST_DEFAULTS["PER_CLAIM_EXPENSE_LIMIT_CENTS"],
        "effective_date": TEST_DEFAULTS["EFFECTIVE_DATE"],
        "expiration_date": TEST_DEFAULTS["EXPIRATION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_adjuster_payload(**overrides) -> dict:
    defaults = {
        "name": "Ada Adjuster",
        "email": "ada@example.com",
        "authority_limit_cents": TEST_DEFAULTS["ADJUSTER_AUTHORITY_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_vendor_payload(**overrides) -> dict:
    defaults = {
        "name": "Vendor Co",
        "vendor_type": "INDEPENDENT_ADJUSTER",
        "credentialed_coverages": ["PROPERTY", "AUTO", "LIABILITY", "WORKERS_COMP"],
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(policy_id, **overrides) -> dict:
    defaults = {
        "policy_id": policy_id,
        "coverage_type": "PROPERTY",
        "loss_date": TEST_DEFAULTS["LOSS_DATE"],
        "reported_date": TEST_DEFAULTS["REPORTED_DATE"],
        "claimant_name": "Claimant Name",
        "description": "Loss description",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(claim_id, assignee_type, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "assignee_type": assignee_type,
        "scope": "FIELD_INSPECTION",
        "inspection_start": "2026-06-16T09:00:00Z",
        "inspection_end": "2026-06-16T11:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_reserve_change_payload(claim_id, reserve_type, delta_cents,
                                  expected_claim_version, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "reserve_type": reserve_type,
        "delta_cents": delta_cents,
        "reason": "reserve adjustment",
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(claim_id, amount_cents, expected_claim_version, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "payment_type": "INDEMNITY",
        "payee_type": "CLAIMANT",
        "payee_name": "Claimant Name",
        "amount_cents": amount_cents,
        "expected_claim_version": expected_claim_version,
    }
    defaults.update(overrides)
    return defaults


def create_vendor_invoice_payload(claim_id, assignment_id, hours, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "assignment_id": assignment_id,
        "hours": hours,
    }
    defaults.update(overrides)
    return defaults


def create_litigation_case_payload(claim_id, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "venue": "Superior Court",
    }
    defaults.update(overrides)
    return defaults


def create_subrogation_case_payload(claim_id, demand_cents, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "at_fault_party": "At-Fault Party",
        "demand_cents": demand_cents,
    }
    defaults.update(overrides)
    return defaults


def create_siu_referral_payload(claim_id, **overrides) -> dict:
    defaults = {
        "claim_id": claim_id,
        "reason": "fraud indicator",
    }
    defaults.update(overrides)
    return defaults


def create_bordereau_report_payload(client_account_id, period_start, period_end, basis, **overrides) -> dict:
    defaults = {
        "client_account_id": client_account_id,
        "period_start": period_start,
        "period_end": period_end,
        "basis": basis,
    }
    defaults.update(overrides)
    return defaults
