"""Payload factories — one per entity, input fields only.

Field names match the PRD exactly. Only client-supplied (input) fields appear
here; system/computed fields are never sent.
"""
import itertools

# Monotonic counter so auto-generated EINs are unique across a single server run.
_ein_counter = itertools.count(1)


def unique_ein() -> str:
    """A unique EIN string (PRD §3.1: ein must be unique across all borrowers)."""
    return f"99-{next(_ein_counter):07d}"


def create_borrower_payload(**overrides) -> dict:
    """POST /borrowers input: business_name, ein, state_code."""
    defaults = {
        "business_name": "Test Business",
        "ein": unique_ein(),
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_loan_application_payload(borrower_id: str, **overrides) -> dict:
    """POST /loan-applications input fields. Defaults score to an A-grade
    application (rev 3,000,000 / debt 1,000,000 / nsf 0 / age 48 -> score 92.0)."""
    defaults = {
        "borrower_id": borrower_id,
        "requested_principal_cents": 1_200_000,
        "term_months": 12,
        "plaid_avg_monthly_revenue_cents": 3_000_000,
        "plaid_monthly_debt_payment_cents": 1_000_000,
        "plaid_nsf_count_90d": 0,
        "plaid_account_age_months": 48,
    }
    defaults.update(overrides)
    return defaults


def create_investor_payload(**overrides) -> dict:
    """POST /investors input: display_name, optional max_single_loan_pct."""
    defaults = {
        "display_name": "Test Investor",
    }
    defaults.update(overrides)
    return defaults


def deposit_payload(amount_cents: int, **overrides) -> dict:
    """POST /investors/{id}/deposit input: amount_cents."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_investment_payload(investor_id: str, loan_id: str, amount_cents: int,
                              expected_loan_version: int, **overrides) -> dict:
    """POST /investments input: investor_id, loan_id, amount_cents, expected_loan_version."""
    defaults = {
        "investor_id": investor_id,
        "loan_id": loan_id,
        "amount_cents": amount_cents,
        "expected_loan_version": expected_loan_version,
    }
    defaults.update(overrides)
    return defaults


def create_repayment_payload(loan_id: str, amount_cents: int, **overrides) -> dict:
    """POST /loans/{id}/repayments input: loan_id, amount_cents, optional kind."""
    defaults = {
        "loan_id": loan_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_payload(loan_id: str, document_type: str = "SERIES_NOTE_PROSPECTUS",
                              **overrides) -> dict:
    """POST /compliance-disclosures input: loan_id, document_type."""
    defaults = {
        "loan_id": loan_id,
        "document_type": document_type,
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc input: to_iso8601."""
    return {"to_iso8601": to_iso8601}
