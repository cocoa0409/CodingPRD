"""Payload factories — one per entity, input fields only."""
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Household
# ---------------------------------------------------------------------------

def create_household_payload(**overrides) -> dict:
    """Build a Household creation payload.

    Defaults: CA, 94110, no extra expenses.
    """
    payload = {
        "state_code": "CA",
        "address_zip": "94110",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Member
# ---------------------------------------------------------------------------

def create_member_payload(**overrides) -> dict:
    """Build a Member creation payload.

    Defaults: 30-year-old adult born in 1990, no income, not disabled/pregnant.
    """
    payload = {
        "full_name": "Test Member",
        "date_of_birth": "1990-01-01",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Merchant
# ---------------------------------------------------------------------------

def create_merchant_payload(**overrides) -> dict:
    """Build a Merchant onboarding payload.

    Defaults: name "Test Merchant", far-future authorization expiry, no pilot.
    """
    payload = {
        "name": "Test Merchant",
        "authorization_expires_at": "2099-12-31T23:59:59.000Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Application (no input fields needed for creation per scaffold)
# ---------------------------------------------------------------------------

def create_application_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Transaction
# ---------------------------------------------------------------------------

def create_transaction_payload(card_id: str, merchant_id: str, **overrides) -> dict:
    """Build a Transaction creation payload.

    Defaults: 1 STAPLE @ $5 x 1, requested amount $5.
    """
    line_items = overrides.pop(
        "line_items",
        [{"item_category": "STAPLE", "unit_price_cents": 500, "quantity": 1}],
    )
    requested = overrides.pop("requested_amount_cents", None)
    if requested is None:
        # default: sum of line items
        requested = sum(li["unit_price_cents"] * li["quantity"] for li in line_items)
    payload = {
        "card_id": card_id,
        "merchant_id": merchant_id,
        "requested_amount_cents": requested,
        "line_items": line_items,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Fraud Case
# ---------------------------------------------------------------------------

def create_fraud_case_payload(household_id: str, **overrides) -> dict:
    """Build a FraudCase open payload."""
    payload = {
        "household_id": household_id,
        "trigger_reason": "MANUAL_REPORT",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ABAWD Waiver
# ---------------------------------------------------------------------------

def create_abawd_waiver_payload(**overrides) -> dict:
    """Build an AbawdWaiver request payload.

    Defaults: WORK_TRAINING_ENROLLED, 3-month window starting 2026-01-01.
    """
    payload = {
        "waiver_kind": "WORK_TRAINING_ENROLLED",
        "effective_from": "2026-01-01T00:00:00.000Z",
        "effective_to": "2026-04-01T00:00:00.000Z",
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Emergency Allotment
# ---------------------------------------------------------------------------

def create_emergency_allotment_payload(**overrides) -> dict:
    """Build an EmergencyAllotment creation payload.

    Defaults: CA, 2026-01 month, max_allotment_table_version=1.
    """
    payload = {
        "state_code": "CA",
        "benefit_month": "2026-01",
        "max_allotment_table_version": 1,
    }
    payload.update(overrides)
    return payload
