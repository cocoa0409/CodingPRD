"""Payload factories — one per entity, input fields only (PRD Sections 3.x).

Each factory supplies sensible defaults for required fields and merges caller
overrides. A module-level counter keeps unique values (sku_code, email, lot_code)
distinct within a single test even though the server DB is empty at test start.
"""
import itertools

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


def order_line(product_id: str, quantity: int) -> dict:
    """One order line object referencing a product and quantity."""
    return {"product_id": product_id, "quantity": quantity}


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku_code": _uniq("SKU"),
        "name": "Test Grow Product",
        "category": "SYSTEM",
        "unit_price_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(**overrides) -> dict:
    defaults = {
        "lot_code": _uniq("LOT"),
        "quantity_on_hand": 100,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": f"{_uniq('cust')}@example.com",
        "full_name": "Test Customer",
    }
    defaults.update(overrides)
    return defaults


def create_commercial_account_payload(**overrides) -> dict:
    defaults = {
        "business_name": "Test Growers Co",
        "credit_limit_cents": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_retail_order_payload(customer_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_commercial_order_payload(lines: list, expected_version: int, **overrides) -> dict:
    defaults = {
        "lines": lines,
        "expected_commercial_account_version": expected_version,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "interval_days": 30,
        "quantity_per_cycle": 2,
    }
    defaults.update(overrides)
    return defaults


def create_consultant_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Consultant",
        "specialty": "VERTICAL_FARM",
        "hourly_rate_cents": 12_000,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(customer_id: str, start_at: str, end_at: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "start_at": start_at,
        "end_at": end_at,
    }
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Studio",
        "seat_capacity": 20,
    }
    defaults.update(overrides)
    return defaults


def create_workshop_session_payload(room_id: str, start_at: str, end_at: str,
                                    capacity: int, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "title": "Test Workshop",
        "start_at": start_at,
        "end_at": end_at,
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


def create_registration_payload(customer_id: str, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_rma_payload(order_id: str, product_id: str, return_quantity: int,
                       reason: str = "defective", **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "product_id": product_id,
        "return_quantity": return_quantity,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults
