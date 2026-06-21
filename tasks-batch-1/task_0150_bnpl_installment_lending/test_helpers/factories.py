"""Payload factories — one per entity, input fields only (PRD §3)."""


def create_merchant_payload(**overrides) -> dict:
    """POST /merchants input: display_name, mdr_bps, settlement_hold_days? (PRD §3.1)."""
    defaults = {
        "display_name": "Test Merchant",
        "mdr_bps": 600,
    }
    defaults.update(overrides)
    return defaults


def create_borrower_payload(**overrides) -> dict:
    """POST /borrowers input: full_name, email, annual_income_cents, soft_credit_score (PRD §3.1)."""
    defaults = {
        "full_name": "Test Borrower",
        "email": "borrower@example.com",
        "annual_income_cents": 8_000_000,
        "soft_credit_score": 760,
    }
    defaults.update(overrides)
    return defaults


def create_application_payload(borrower_id: str, merchant_id: str, **overrides) -> dict:
    """POST /applications input: borrower_id, merchant_id, cart_amount_cents,
    plan_type, term_months?, requested_down_payment_cents? (PRD §3.2)."""
    defaults = {
        "borrower_id": borrower_id,
        "merchant_id": merchant_id,
        "cart_amount_cents": 100_000,
        "plan_type": "PAY_IN_4",
        "requested_down_payment_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_disclosure_acceptance_payload(application_id: str, accepted: bool = True, **overrides) -> dict:
    """POST /disclosure-acceptances input: application_id, accepted (PRD §3.4)."""
    defaults = {
        "application_id": application_id,
        "accepted": accepted,
    }
    defaults.update(overrides)
    return defaults


def create_loan_payload(application_id: str, **overrides) -> dict:
    """POST /loans input: application_id (PRD §3.4)."""
    defaults = {"application_id": application_id}
    defaults.update(overrides)
    return defaults


def create_payment_payload(loan_id: str, amount_cents: int, **overrides) -> dict:
    """POST /payments input: loan_id, amount_cents, source? (PRD §3.5)."""
    defaults = {
        "loan_id": loan_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(loan_id: str, return_amount_cents: int, **overrides) -> dict:
    """POST /returns input: loan_id, return_amount_cents (PRD §3.9)."""
    defaults = {
        "loan_id": loan_id,
        "return_amount_cents": return_amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_autopay_mandate_payload(loan_id: str, **overrides) -> dict:
    """POST /autopay-mandates input: loan_id (PRD §3.7)."""
    defaults = {"loan_id": loan_id}
    defaults.update(overrides)
    return defaults


def decision_payload(decision: str) -> dict:
    """POST /applications/{id}/decision input: decision (APPROVE/COUNTER/DECLINE)."""
    return {"decision": decision}


def revise_payload(requested_down_payment_cents: int) -> dict:
    """POST /applications/{id}/revise input: requested_down_payment_cents."""
    return {"requested_down_payment_cents": requested_down_payment_cents}


def clock_payload(to_iso8601: str) -> dict:
    """POST /_clock/set_current_utc input: to_iso8601."""
    return {"to_iso8601": to_iso8601}


def loan_version_payload(expected_loan_version: int) -> dict:
    """OCC payload for POST /loans/{id}/default and /cancel (PRD §2.7)."""
    return {"expected_loan_version": expected_loan_version}
