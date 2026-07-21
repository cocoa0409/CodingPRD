"""Payload factories — one per creatable resource, input fields only.

Field names are PRD-exact. Only fields the client supplies (source: input) are
included; all computed/system fields are omitted.
"""
import itertools

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


def create_portfolio_payload(**overrides) -> dict:
    """POST /portfolios (PRD §2.7)."""
    defaults = {
        "name": _uniq("Book"),
        "exposure_cap_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_applicant_payload(**overrides) -> dict:
    """POST /applicants (PRD §3.1). Defaults describe a tier-A applicant
    (credit 740, monthly income 1,000,000, dti 0.20)."""
    defaults = {
        "full_name": "Test Renter",
        "email": f"{_uniq('renter')}@example.com",
        "annual_income_cents": 12_000_000,
        "credit_score": 740,
        "monthly_obligations_cents": 200_000,
        "employment_type": "SALARIED",
    }
    defaults.update(overrides)
    return defaults


def create_landlord_payload(**overrides) -> dict:
    """POST /landlords (PRD §3.3)."""
    defaults = {
        "legal_name": "Test Landlord LLC",
        "email": f"{_uniq('landlord')}@example.com",
    }
    defaults.update(overrides)
    return defaults


def create_guarantee_payload(portfolio_id: str, applicant_id: str, **overrides) -> dict:
    """POST /guarantees (PRD §3.2). Defaults describe the standard guarantee
    (rent 249999, coverage 6, term 12)."""
    defaults = {
        "portfolio_id": portfolio_id,
        "applicant_id": applicant_id,
        "unit_id": _uniq("U"),
        "monthly_rent_cents": 249_999,
        "coverage_months": 6,
        "term_months": 12,
        "lease_start_date": "2026-08-01T00:00:00Z",
        "lease_end_date": "2027-08-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(guarantee_id: str, landlord_id: str, unit_id: str,
                             **overrides) -> dict:
    """POST /agreements (PRD §3.3)."""
    defaults = {
        "guarantee_id": guarantee_id,
        "landlord_id": landlord_id,
        "unit_id": unit_id,
        "coverage_start_date": "2026-08-01T00:00:00Z",
        "coverage_end_date": "2027-08-01T00:00:00Z",
        "max_coverage_cents": 2_000_000,
        "notice_period_days": 60,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(expected_guarantee_version: int, **overrides) -> dict:
    """POST /guarantees/{id}/claims (PRD §3.6)."""
    defaults = {
        "expected_guarantee_version": expected_guarantee_version,
        "default_date": "2026-09-01T00:00:00Z",
        "missed_months": 5,
        "acceleration_requested": False,
    }
    defaults.update(overrides)
    return defaults


def pay_fee_payload(amount_cents: int, **overrides) -> dict:
    """POST /guarantees/{id}/pay-fee (PRD §3.4)."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_installment_payload(amount_cents: int, **overrides) -> dict:
    """POST /recovery-plans/{id}/installments (PRD §3.7)."""
    defaults = {"amount_cents": amount_cents}
    defaults.update(overrides)
    return defaults


def create_compliance_review_payload(guarantee_id: str, reason: str = "KYC_MISMATCH",
                                     **overrides) -> dict:
    """POST /compliance-reviews (PRD §3.8)."""
    defaults = {"guarantee_id": guarantee_id, "reason": reason}
    defaults.update(overrides)
    return defaults
