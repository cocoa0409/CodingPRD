"""Payload factories — one per creatable entity, input fields only.

Each factory provides sensible defaults and accepts **overrides so tests can
control the values they care about. Unique fields (stock_number, serial_number,
sku) accept overrides; callers needing many entities should pass distinct values.
"""
import itertools

_counter = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "stock_number": _uniq("STK"),
        "condition": "NEW",
        "model_code": "5045E",
        "serial_number": _uniq("SN"),
        "dealer_cost_cents": 3000000,
        "list_price_cents": 4000000,
    }
    defaults.update(overrides)
    return defaults


def create_floor_plan_note_payload(unit_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "principal_cents": 7000000,
        "annual_rate_bps": 850,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Farm",
        "customer_type": "RETAIL",
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "model_code": "5065E",
        "serial_number": _uniq("SN-TR"),
        "engine_hours": 800,
        "condition_grade": "GOOD",
        "base_value_cents": 4000000,
    }
    defaults.update(overrides)
    return defaults


def create_deal_payload(unit_id: str, customer_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "customer_id": customer_id,
        "deal_type": "SALE",
        "sale_price_cents": 6000000,
    }
    defaults.update(overrides)
    return defaults


def create_auction_lot_payload(unit_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "reserve_price_cents": 4000000,
        "opens_at": "2026-01-01T00:00:00Z",
        "closes_at": "2026-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_bid_payload(bidder_customer_id: str, amount_cents: int, **overrides) -> dict:
    defaults = {
        "bidder_customer_id": bidder_customer_id,
        "amount_cents": amount_cents,
    }
    defaults.update(overrides)
    return defaults


def create_part_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "description": "test part",
        "category": "MECHANICAL",
        "unit_price_cents": 25000,
        "on_hand_qty": 5,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(unit_id: str, customer_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "customer_id": customer_id,
        "complaint": "test complaint",
        "labor_rate_cents": 14000,
        "flat_rate_hours": 2.0,
    }
    defaults.update(overrides)
    return defaults


def create_part_line_payload(part_id: str, quantity: int = 1, **overrides) -> dict:
    defaults = {
        "part_id": part_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(unit_id: str, **overrides) -> dict:
    defaults = {
        "unit_id": unit_id,
        "claim_type": "WARRANTY",
    }
    defaults.update(overrides)
    return defaults


def create_whole_goods_order_payload(customer_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "model_code": "5075E",
        "season_program": "EARLY_ORDER",
        "quantity": 1,
        "unit_msrp_cents": 5000000,
    }
    defaults.update(overrides)
    return defaults
