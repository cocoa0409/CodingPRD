"""Payload factories — one per entity, input fields only.

Field names are PRD-exact. Only `source: input` fields appear; computed/system
fields (status, totals, availability, version, ...) are never sent.
"""
from .constants import FAR_EXPIRY_ISO


def create_customer_payload(**overrides) -> dict:
    """Input fields: email, full_name, home_zone, (optional referrer_id)."""
    defaults = {
        "email": "cust@example.com",
        "full_name": "Test Customer",
        "home_zone": "Z1",
    }
    defaults.update(overrides)
    return defaults


def create_sku_payload(**overrides) -> dict:
    """Input fields: name, category, storage_class, unit_price_cents, (optional allergens)."""
    defaults = {
        "name": "Test Sauce",
        "category": "HOT_SAUCE",
        "storage_class": "AMBIENT",
        "unit_price_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(sku_id: str, **overrides) -> dict:
    """Input fields: sku_id, lot_code, produced_units, expiry_iso."""
    defaults = {
        "sku_id": sku_id,
        "lot_code": "L-TEST",
        "produced_units": 50,
        "expiry_iso": FAR_EXPIRY_ISO,
    }
    defaults.update(overrides)
    return defaults


def release_lot_payload(expected_lot_version: int, **overrides) -> dict:
    """Input field: expected_lot_version (OCC, PRD §2.8)."""
    defaults = {"expected_lot_version": expected_lot_version}
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id: str, sku_id: str, **overrides) -> dict:
    """Input fields: customer_id, sku_id, tier, cadence_days."""
    defaults = {
        "customer_id": customer_id,
        "sku_id": sku_id,
        "tier": "STARTER",
        "cadence_days": 14,
    }
    defaults.update(overrides)
    return defaults


def swap_subscription_payload(pending_swap_sku_id: str, expected_subscription_version: int, **overrides) -> dict:
    """Input fields: pending_swap_sku_id, expected_subscription_version (OCC, PRD §2.8)."""
    defaults = {
        "pending_swap_sku_id": pending_swap_sku_id,
        "expected_subscription_version": expected_subscription_version,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, **overrides) -> dict:
    """Input fields: customer_id, order_kind, ship_zone, (optional subscription_id,
    gift_recipient_email, gift_box_count, requested_redeem_points)."""
    defaults = {
        "customer_id": customer_id,
        "order_kind": "ONE_TIME",
        "ship_zone": "Z1",
    }
    defaults.update(overrides)
    return defaults


def create_order_line_payload(sku_id: str, quantity: int = 1, **overrides) -> dict:
    """Input fields: sku_id, quantity."""
    defaults = {"sku_id": sku_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def pay_order_payload(outcome: str = "SUCCEEDED", **overrides) -> dict:
    """Input field: outcome (simulated payment outcome, PRD §3.4)."""
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_bulk_quote_payload(corporate_buyer_id: str, sku_id: str, quantity: int = 1, **overrides) -> dict:
    """Input fields: corporate_buyer_id, sku_id, quantity, (optional gift_box_count)."""
    defaults = {
        "corporate_buyer_id": corporate_buyer_id,
        "sku_id": sku_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(referrer_id: str, referred_id: str, **overrides) -> dict:
    """Input fields: referrer_id, referred_id."""
    defaults = {"referrer_id": referrer_id, "referred_id": referred_id}
    defaults.update(overrides)
    return defaults


def create_winback_offer_payload(customer_id: str, discount_pct: float = 0.20,
                                 expires_iso: str = "2026-12-31T00:00:00Z", **overrides) -> dict:
    """Input fields: customer_id, discount_pct, expires_iso."""
    defaults = {
        "customer_id": customer_id,
        "discount_pct": discount_pct,
        "expires_iso": expires_iso,
    }
    defaults.update(overrides)
    return defaults
