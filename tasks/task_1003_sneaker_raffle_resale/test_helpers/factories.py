"""Payload factories — one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    """Return a process-unique token so payloads never collide within a run."""
    return f"{prefix}{next(_seq)}"


def create_account_payload(**overrides) -> dict:
    defaults = {
        "email": f"{_uniq('user')}@example.com",
        "full_name": "Test Account",
    }
    defaults.update(overrides)
    return defaults


def create_sku_payload(**overrides) -> dict:
    defaults = {
        "style_code": _uniq("SC-"),
        "name": "Test Sneaker",
        "brand": "Nike",
        "retail_price_cents": 20000,
        # release_category is optional (defaults to GENERAL server-side)
    }
    defaults.update(overrides)
    return defaults


def create_authenticator_payload(**overrides) -> dict:
    defaults = {
        "name": f"Auth {_uniq('')}",
        "location_code": "NJ1",
        # daily_capacity is optional (defaults to 8 server-side)
    }
    defaults.update(overrides)
    return defaults


def create_release_payload(**overrides) -> dict:
    defaults = {
        "sku_id": None,
        "allocated_quantity": 1,
        "release_price_cents": 20000,
        "entry_opens_at": "2026-07-05T00:00:00Z",
        "entry_closes_at": "2026-07-06T00:00:00Z",
        "purchase_opens_at": "2026-07-06T01:00:00Z",
        "purchase_closes_at": "2026-07-07T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_listing_payload(**overrides) -> dict:
    defaults = {
        "sku_id": None,
        "seller_account_id": None,
        "size": "10",
        "condition": "DEADSTOCK",
        "pricing_mode": "FIXED",
        "ask_price_cents": 30000,
        # expires_at is optional (null = good-till-cancelled)
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(**overrides) -> dict:
    defaults = {
        "sku_id": None,
        "buyer_account_id": None,
        "size": "10",
        "amount_cents": 20000,
        # expires_at is optional
    }
    defaults.update(overrides)
    return defaults


def create_consignment_item_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "seller_account_id": None,
        "sku_id": None,
        "declared_condition_grade": "DEADSTOCK",
        "declared_box_grade": "PERFECT",
        "declared_accessories_complete": True,
    }
    defaults.update(overrides)
    return defaults


def create_dispute_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "filed_by_account_id": None,
        "reason": "INAUTHENTIC",
    }
    defaults.update(overrides)
    return defaults
