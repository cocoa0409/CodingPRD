"""Payload factories — one per entity, input fields only.

Only fields the client supplies on create are included. Computed/system fields
(id, status, wallet_credit_cents, version, timestamps, ...) are never sent.
"""
import itertools

_email_counter = itertools.count(1)
_sku_counter = itertools.count(1)
_table_number_counter = itertools.count(1)


def unique_email(prefix="member") -> str:
    return f"{prefix}{next(_email_counter)}@example.com"


def unique_sku(prefix="SKU") -> str:
    return f"{prefix}-{next(_sku_counter)}"


def next_table_number() -> int:
    return next(_table_number_counter)


def create_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": "BRONZE",
        "monthly_fee_cents": 3000,
        "table_discount_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(**overrides) -> dict:
    defaults = {
        "email": unique_email(),
        "full_name": "Test Member",
        "plan_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_table_payload(**overrides) -> dict:
    defaults = {
        "table_number": next_table_number(),
        "table_type": "POOL_7FT",
        "seat_capacity": 4,
        "hourly_rate_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_reservation_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "table_id": None,
        "start_at": "2026-07-09T10:00:00Z",
        "end_at": "2026-07-09T11:00:00Z",
        "party_size": 2,
    }
    defaults.update(overrides)
    return defaults


def create_session_payload(**overrides) -> dict:
    defaults = {
        "table_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_fnb_order_payload(**overrides) -> dict:
    defaults = {
        "session_id": None,
        "line_items": [{"name": "Cola", "unit_price_cents": 300, "qty": 1}],
    }
    defaults.update(overrides)
    return defaults


def create_tournament_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Cup",
        "format": "SINGLE_ELIM",
        "entry_fee_cents": 0,
        "max_entries": 8,
    }
    defaults.update(overrides)
    return defaults


def create_tournament_entry_payload(**overrides) -> dict:
    defaults = {
        "tournament_id": None,
        "member_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": unique_sku(),
        "name": "Test Product",
        "category": "ACCESSORY",
        "unit_price_cents": 500,
        "stock_qty": 5,
    }
    defaults.update(overrides)
    return defaults


def create_repair_order_payload(**overrides) -> dict:
    defaults = {
        "member_id": None,
        "service_type": "CUE_RETIP",
        "quote_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_event_payload(**overrides) -> dict:
    defaults = {
        "host_member_id": None,
        "table_count": 1,
        "start_at": "2026-07-04T10:00:00Z",
        "end_at": "2026-07-04T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults
