"""Payload factories — one per creatable/updatable resource, input fields only."""
from .constants import TEST_DEFAULTS

LOAN_COUNTER = {"n": 0}


def _next_loan_number() -> str:
    LOAN_COUNTER["n"] += 1
    return f"LN-{LOAN_COUNTER['n']:04d}"


def create_loan_payload(**overrides) -> dict:
    """escrow_required is optional (defaults true) — include only when given."""
    defaults = {
        "loan_number": _next_loan_number(),
        "borrower_name": "Test Borrower",
        "principal_balance_cents": TEST_DEFAULTS["PRINCIPAL_BALANCE_CENTS"],
        "monthly_pi_cents": TEST_DEFAULTS["MONTHLY_PI_CENTS"],
        "closing_date": TEST_DEFAULTS["CLOSING_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_payee_payload(**overrides) -> dict:
    defaults = {
        "payee_type": "TAX_AUTHORITY",
        "legal_name": "County Treasurer",
        "remit_to_address": "1 Civic Center",
        "ach_routing_mask": "****1234",
    }
    defaults.update(overrides)
    return defaults


def create_line_item_payload(payee_id: str, **overrides) -> dict:
    defaults = {
        "payee_id": payee_id,
        "expense_type": "PROPERTY_TAX",
        "expected_annual_amount_cents": 240_000,
        "installments_per_year": 2,
        "first_due_date": "2026-12-15",
    }
    defaults.update(overrides)
    return defaults


def patch_line_item_payload(**overrides) -> dict:
    return dict(overrides)


def create_disbursement_payload(line_item_id: str, payee_id: str, **overrides) -> dict:
    defaults = {
        "line_item_id": line_item_id,
        "payee_id": payee_id,
        "amount_cents": 30_000,
        "due_date": "2026-12-20",
        "scheduled_release_date": "2026-12-01",
    }
    defaults.update(overrides)
    return defaults


def patch_disbursement_payload(expected_disbursement_version, **overrides) -> dict:
    payload = {"expected_disbursement_version": expected_disbursement_version}
    payload.update(overrides)
    return payload


def create_deposit_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 60_000,
        "effective_date": "2026-08-10",
    }
    defaults.update(overrides)
    return defaults


def create_insurance_policy_payload(**overrides) -> dict:
    defaults = {
        "policy_type": "HAZARD",
        "carrier_name": "Carrier A",
        "policy_number": "POL-1",
        "coverage_start_date": "2026-01-01",
        "coverage_end_date": "2027-01-01",
        "annual_premium_cents": 120_000,
    }
    defaults.update(overrides)
    return defaults


def reinstate_policy_payload(**overrides) -> dict:
    defaults = {
        "new_coverage_start_date": "2027-02-05",
        "new_coverage_end_date": "2028-02-05",
    }
    defaults.update(overrides)
    return defaults


def charge_force_placement_payload(**overrides) -> dict:
    defaults = {"fp_premium_cents": 182_500}
    defaults.update(overrides)
    return defaults


def create_tax_record_payload(**overrides) -> dict:
    defaults = {
        "parcel_number": "P-1",
        "tax_year": 2026,
        "installment_sequence": 1,
        "amount_due_cents": 300_000,
        "due_date": "2026-08-01",
        "monthly_penalty_rate_bps": 150,
        "penalty_method": "SIMPLE",
    }
    defaults.update(overrides)
    return defaults


def mark_tax_paid_payload(disbursement_id: str) -> dict:
    return {"disbursement_id": disbursement_id}


def create_analysis_payload(expected_escrow_account_version, **overrides) -> dict:
    defaults = {
        "analysis_year": 2027,
        "projection_start_date": "2026-09-01",
        "method": "PROSPECTIVE",
        "expected_escrow_account_version": expected_escrow_account_version,
    }
    defaults.update(overrides)
    return defaults


def acknowledge_notice_payload(**overrides) -> dict:
    return dict(overrides)


def create_advance_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 50_000,
        "reason": "MANUAL_CORRECTION",
    }
    defaults.update(overrides)
    return defaults


def recover_advance_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def create_error_case_payload(**overrides) -> dict:
    defaults = {
        "error_type": "OTHER_COVERED",
        "description": "Borrower-asserted error",
    }
    defaults.update(overrides)
    return defaults


def assign_case_payload(assigned_to_user_id: str) -> dict:
    return {"assigned_to_user_id": assigned_to_user_id}


def resolve_case_payload(**overrides) -> dict:
    defaults = {"outcome": "NO_ERROR"}
    defaults.update(overrides)
    return defaults


def dismiss_case_payload(**overrides) -> dict:
    defaults = {"dismissal_reason": "Not a covered error"}
    defaults.update(overrides)
    return defaults
