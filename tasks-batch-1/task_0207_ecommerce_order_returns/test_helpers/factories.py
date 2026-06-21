"""Payload factories — one per entity, input fields only.

Field names mirror the PRD request bodies exactly. Optional fields with declared
server-side defaults (Product.restocking_fee_bps=0, Product.final_sale=false,
Warehouse.accepts_returns=true, Order.promo_flat_cents=0) are omitted unless the
caller overrides them, so a created resource shows the PRD-declared defaults.
"""
import itertools

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": _uniq("cust") + "@example.com",
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("WH").upper(),
        "name": "Test Warehouse",
        "fulfillment_priority": 1,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU").upper(),
        "title": "Test Product",
        "unit_price_cents": 1000,
        "tax_rate_bps": 0,
        "return_window_days": 30,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_payload(product_id, warehouse_id, on_hand_qty=10, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "warehouse_id": warehouse_id,
        "on_hand_qty": on_hand_qty,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id, qty=1, **overrides) -> dict:
    defaults = {"product_id": product_id, "qty": qty}
    defaults.update(overrides)
    return defaults


def checkout_payload(expected_order_version, **overrides) -> dict:
    defaults = {"expected_order_version": expected_order_version}
    defaults.update(overrides)
    return defaults


def create_shipment_payload(warehouse_id, lines, **overrides) -> dict:
    """`lines` is a list of {reservation_id, qty} dicts."""
    defaults = {"warehouse_id": warehouse_id, "lines": lines}
    defaults.update(overrides)
    return defaults


def open_return_payload(reason, resolution, lines, **overrides) -> dict:
    """`lines` is a list of return-line dicts: {order_line_id, return_qty[, exchange_product_id]}."""
    defaults = {"reason": reason, "resolution": resolution, "lines": lines}
    defaults.update(overrides)
    return defaults


def approve_return_payload(expected_return_version, **overrides) -> dict:
    defaults = {"expected_return_version": expected_return_version}
    defaults.update(overrides)
    return defaults


def restock_payload(warehouse_id, **overrides) -> dict:
    defaults = {"warehouse_id": warehouse_id}
    defaults.update(overrides)
    return defaults


def credit_adjustment_payload(amount_cents, kind, **overrides) -> dict:
    defaults = {"amount_cents": amount_cents, "kind": kind}
    defaults.update(overrides)
    return defaults
