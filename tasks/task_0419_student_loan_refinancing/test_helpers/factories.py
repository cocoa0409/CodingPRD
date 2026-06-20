"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix="b"):
    return f"{prefix}.{uuid.uuid4().hex[:12]}@x.com"


def _unique_pool_code(prefix="POOL"):
    return f"{prefix}-{uuid.uuid4().hex[:10].upper()}"


def create_borrower_payload(**overrides) -> dict:
    """Borrower input fields (PRD 3.1): email, full_name, annual_income_cents, fico_band."""
    defaults = {
        "email": _unique_email(),
        "full_name": "Test Borrower",
        "annual_income_cents": 30_000_000,
        "fico_band": "PRIME",
    }
    defaults.update(overrides)
    return defaults


def create_abs_pool_payload(**overrides) -> dict:
    """AbsPool input fields (PRD 3.1)."""
    defaults = {
        "pool_code": _unique_pool_code(),
        "max_principal_cents": 20_000_000,
        "min_fico_band": "SUBPRIME",
        "allowed_rate_type": "ANY",
    }
    defaults.update(overrides)
    return defaults


def create_rate_grid_entry_payload(**overrides) -> dict:
    """RateGridEntry input fields (PRD 3.1). index_apr_bps optional (defaults to 0)."""
    defaults = {
        "rate_type": "FIXED",
        "term_months": 120,
        "min_fico_band": "NEAR_PRIME",
        "base_apr_bps": 650,
        "index_apr_bps": 0,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(**overrides) -> dict:
    """Application input fields (PRD 3.2)."""
    defaults = {
        "borrower_id": None,
        "requested_principal_cents": 5_000_000,
        "requested_term_months": 120,
        "requested_rate_type": "FIXED",
    }
    defaults.update(overrides)
    return defaults


def create_cosigner_payload(**overrides) -> dict:
    """Cosigner input fields (PRD 3.3)."""
    defaults = {
        "application_id": None,
        "cosigner_email": _unique_email("c"),
        "cosigner_annual_income_cents": 6_000_000,
    }
    defaults.update(overrides)
    return defaults


def lock_offer_payload(expected_application_version, **overrides) -> dict:
    """Offer-lock input fields (PRD 3.4). expected_application_version required."""
    defaults = {
        "expected_application_version": expected_application_version,
        "autopay_elected": False,
    }
    defaults.update(overrides)
    return defaults


def create_disbursement_payload(loan_id, **overrides) -> dict:
    """Disbursement input fields (PRD 3.8)."""
    defaults = {
        "loan_id": loan_id,
        "prior_servicer_name": "Prior Servicer",
        "payoff_amount_cents": 2_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents, due_date, **overrides) -> dict:
    """Payment input fields (PRD 3.9). paid_at optional."""
    defaults = {
        "amount_cents": amount_cents,
        "due_date": due_date,
    }
    defaults.update(overrides)
    return defaults


def create_forbearance_payload(**overrides) -> dict:
    """ForbearancePlan input fields (PRD 3.11)."""
    defaults = {
        "reason_code": "JOB_LOSS",
        "months_requested": 3,
    }
    defaults.update(overrides)
    return defaults
