"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix: str = "tp") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def create_taxpayer_payload(**overrides) -> dict:
    """Taxpayer registration. prior_year_* default to 0 (PRD §3.1)."""
    defaults = {
        "email": _unique_email(),
        "full_name": "Test Taxpayer",
        "filing_status": "SINGLE",
    }
    defaults.update(overrides)
    return defaults


def create_tax_return_payload(taxpayer_id: str, **overrides) -> dict:
    """Open a draft return. deduction_method defaults to STANDARD server-side."""
    defaults = {
        "taxpayer_id": taxpayer_id,
        "tax_year": 2025,
        "filing_status": "SINGLE",
    }
    defaults.update(overrides)
    return defaults


def create_income_document_payload(**overrides) -> dict:
    """Income document. Only doc_type, payer_name, box_amount_cents are required;
    withholding and 1099-specific fields default server-side."""
    defaults = {
        "doc_type": "W2",
        "payer_name": "Acme",
        "box_amount_cents": 8_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_schedule_payload(schedule_type: str, **overrides) -> dict:
    defaults = {
        "schedule_type": schedule_type,
    }
    defaults.update(overrides)
    return defaults


def create_dependent_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Dependent",
        "age_years": 10,
    }
    defaults.update(overrides)
    return defaults


def create_credit_claim_payload(credit_type: str, **overrides) -> dict:
    defaults = {
        "credit_type": credit_type,
    }
    defaults.update(overrides)
    return defaults


def create_estimated_tax_payment_payload(return_id: str, **overrides) -> dict:
    defaults = {
        "return_id": return_id,
        "quarter": "Q1",
        "amount_cents": 100_000,
        "paid_on": "2025-04-10T00:00:00Z",
        "period_start": "2025-01-01T00:00:00Z",
        "period_end": "2025-04-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def efile_payload(expected_return_version: int, **overrides) -> dict:
    defaults = {
        "signature_pin": "12345",
        "expected_return_version": expected_return_version,
    }
    defaults.update(overrides)
    return defaults


def acknowledge_payload(outcome: str, ack_code: str = "A0000", **overrides) -> dict:
    defaults = {
        "outcome": outcome,
        "ack_code": ack_code,
    }
    defaults.update(overrides)
    return defaults


def create_amended_return_payload(original_return_id: str, taxpayer_id: str,
                                  expected_return_version: int, **overrides) -> dict:
    defaults = {
        "original_return_id": original_return_id,
        "taxpayer_id": taxpayer_id,
        "corrected_balance_due_cents": 40_000,
        "correction_period_start": "2025-01-01T00:00:00Z",
        "correction_period_end": "2025-06-30T00:00:00Z",
        "expected_return_version": expected_return_version,
    }
    defaults.update(overrides)
    return defaults
