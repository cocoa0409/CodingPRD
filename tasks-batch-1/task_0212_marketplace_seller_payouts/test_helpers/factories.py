"""Payload factories — one per entity, input fields only (PRD Section 3)."""
import itertools

# Monotonic counter so factory-built sellers get unique emails (email is unique
# per PRD §3.1). Each test runs against a fresh DB, but a single test may create
# several sellers, so uniqueness within a test still matters.
_email_counter = itertools.count(1)


def _next_email(prefix: str = "seller") -> str:
    return f"{prefix}-{next(_email_counter)}@example.com"


def create_seller_payload(**overrides) -> dict:
    """Seller registration (PRD §3.1). Inputs: legal_name, email, country_code,
    tax_classification, tin_last4."""
    defaults = {
        "legal_name": "Test Seller LLC",
        "email": _next_email(),
        "country_code": "US",
        "tax_classification": "LLC",
        "tin_last4": "1234",
    }
    defaults.update(overrides)
    return defaults


def create_payout_method_payload(seller_id: str, **overrides) -> dict:
    """Payout method (PRD §3.3). Inputs: seller_id, method_type, account_last4, currency."""
    defaults = {
        "seller_id": seller_id,
        "method_type": "ACH",
        "account_last4": "5678",
        "currency": "USD",
    }
    defaults.update(overrides)
    return defaults


def create_fee_schedule_payload(**overrides) -> dict:
    """Fee schedule (PRD §3.4). Inputs: category, commission_bps, fixed_fee_cents,
    payment_processing_bps, payment_processing_fixed_cents, reserve_pct_standard,
    reserve_pct_elevated, reserve_pct_high, maturation_days."""
    defaults = {
        "category": "ELECTRONICS",
        "commission_bps": 1500,
        "fixed_fee_cents": 50,
        "payment_processing_bps": 290,
        "payment_processing_fixed_cents": 30,
        "reserve_pct_standard": 0,
        "reserve_pct_elevated": 20,
        "reserve_pct_high": 50,
        "maturation_days": 7,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(seller_id: str, **overrides) -> dict:
    """Order (PRD §3.4). Inputs: seller_id, category, gross_amount_cents."""
    defaults = {
        "seller_id": seller_id,
        "category": "ELECTRONICS",
        "gross_amount_cents": 10000,
    }
    defaults.update(overrides)
    return defaults


def create_refund_payload(order_id: str, **overrides) -> dict:
    """Refund (PRD §3.6). Inputs: order_id, refund_amount_cents, reason."""
    defaults = {
        "order_id": order_id,
        "refund_amount_cents": 4000,
        "reason": "DAMAGED",
    }
    defaults.update(overrides)
    return defaults


def create_chargeback_payload(order_id: str, **overrides) -> dict:
    """Chargeback (PRD §3.7). Input: order_id."""
    defaults = {"order_id": order_id}
    defaults.update(overrides)
    return defaults


def create_dispute_payload(order_id: str, **overrides) -> dict:
    """Dispute / A-to-Z claim (PRD §3.8). Inputs: order_id, claim_type."""
    defaults = {
        "order_id": order_id,
        "claim_type": "ITEM_NOT_RECEIVED",
    }
    defaults.update(overrides)
    return defaults


def create_payout_payload(seller_id: str, **overrides) -> dict:
    """Payout schedule (PRD §3.9). Input: seller_id."""
    defaults = {"seller_id": seller_id}
    defaults.update(overrides)
    return defaults


def create_tax_form_payload(seller_id: str, **overrides) -> dict:
    """1099-K draft (PRD §3.11). Inputs: seller_id, tax_year."""
    defaults = {
        "seller_id": seller_id,
        "tax_year": 2026,
    }
    defaults.update(overrides)
    return defaults


def create_balance_statement_payload(seller_id: str, **overrides) -> dict:
    """Balance statement (PRD §3.12). Inputs: seller_id, period_year, period_month."""
    defaults = {
        "seller_id": seller_id,
        "period_year": 2026,
        "period_month": 1,
    }
    defaults.update(overrides)
    return defaults
