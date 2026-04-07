"""
Payload factories for e-commerce marketplace entities.

Each factory returns a dict with sensible defaults for all source=input fields,
supporting **overrides to customize any field.
"""

import uuid
from datetime import datetime, timedelta, timezone


def _now_iso() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _future_iso(days: int = 7) -> str:
    """Return a future UTC time as ISO 8601 string."""
    dt = datetime.now(timezone.utc) + timedelta(days=days)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ─── Shop ────────────────────────────────────────────────

def create_shop_payload(**overrides) -> dict:
    """Create a Shop payload with sensible defaults."""
    payload = {
        "shop_name": "Test Shop",
        "owner_id": "seller-001",
        "description": "A test shop for automated testing",
        "discount_strategy": "PERCENTAGE_FIRST",
    }
    payload.update(overrides)
    return payload


# ─── Product ─────────────────────────────────────────────

def create_product_payload(**overrides) -> dict:
    """Create a Product payload with sensible defaults."""
    payload = {
        "product_name": "Test Product",
        "category": "electronics",
        "base_price": 99.99,
        "inventory_count": 100,
    }
    payload.update(overrides)
    return payload


# ─── Promotion ───────────────────────────────────────────

def create_promotion_payload(**overrides) -> dict:
    """Create a Promotion payload with sensible defaults."""
    payload = {
        "promo_name": "Test Promotion",
        "promo_type": "PERCENTAGE",
        "promo_value": 10,
        "promo_threshold": 0,
        "stackable": False,
        "priority": 1,
        "applicable_categories": [],
        "start_time": _now_iso(),
        "end_time": _future_iso(7),
    }
    payload.update(overrides)
    return payload


# ─── Order ───────────────────────────────────────────────

def create_order_payload(shop_id: str, items: list, **overrides) -> dict:
    """
    Create an Order payload.

    Parameters
    ----------
    shop_id : str
        The shop this order is placed with.
    items : list[dict]
        List of {"product_id": ..., "quantity": ...} dicts.
    **overrides
        Any additional or overriding fields.
    """
    payload = {
        "shop_id": shop_id,
        "shipping_address": "123 Test Street, Test City, TC 12345",
        "items": items,
    }
    payload.update(overrides)
    return payload


# ─── Payment ─────────────────────────────────────────────

def create_payment_payload(**overrides) -> dict:
    """Create a Payment payload with sensible defaults."""
    payload = {
        "payment_method": "CREDIT_CARD",
        "transaction_ref": str(uuid.uuid4()),
    }
    payload.update(overrides)
    return payload


# ─── Refund ──────────────────────────────────────────────

def create_refund_payload(refund_type: str = "FULL", **overrides) -> dict:
    """
    Create a Refund payload.

    Parameters
    ----------
    refund_type : str
        "FULL" or "PARTIAL". For PARTIAL, pass refund_items in overrides.
    **overrides
        Any additional or overriding fields.
    """
    payload = {
        "reason": "Customer requested refund",
        "refund_type": refund_type,
    }
    if refund_type == "PARTIAL" and "refund_items" not in overrides:
        # Caller must supply refund_items for PARTIAL; leave empty as reminder
        payload["refund_items"] = []
    payload.update(overrides)
    return payload


# ─── Settlement ──────────────────────────────────────────

def create_settlement_payload(**overrides) -> dict:
    """Create a Settlement payload with sensible defaults."""
    payload = {
        "period_start": _now_iso(),
        "period_end": _future_iso(30),
    }
    payload.update(overrides)
    return payload
