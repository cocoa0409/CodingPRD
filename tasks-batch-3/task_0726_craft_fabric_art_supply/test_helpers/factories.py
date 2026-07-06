"""Payload factories - one per entity, input fields only."""
import itertools

_seq = itertools.count(1)


def _uniq(prefix: str) -> str:
    return f"{prefix}-{next(_seq)}"


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "email": _uniq("cust") + "@example.com",
        "full_name": "Test Customer",
        "home_store_code": "CA01",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _uniq("SKU"),
        "name": "Test Product",
        "sell_mode": "UNIT",
        "unit_price_cents": 500,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_lot_payload(**overrides) -> dict:
    defaults = {"on_hand_yards": 100}
    defaults.update(overrides)
    return defaults


def create_coupon_payload(**overrides) -> dict:
    defaults = {
        "code": _uniq("CPN"),
        "discount_type": "PERCENT",
        "value": 0.1,
        "priority": 1,
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_to": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id, **overrides) -> dict:
    defaults = {"customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_order_line_payload(product_id, requested_yards, **overrides) -> dict:
    defaults = {"product_id": product_id, "requested_yards": requested_yards}
    defaults.update(overrides)
    return defaults


def create_room_payload(**overrides) -> dict:
    defaults = {"name": _uniq("Room")}
    defaults.update(overrides)
    return defaults


def create_workshop_payload(**overrides) -> dict:
    defaults = {"title": _uniq("Workshop")}
    defaults.update(overrides)
    return defaults


def create_session_payload(room_id, starts_at, ends_at, capacity, **overrides) -> dict:
    defaults = {
        "room_id": room_id,
        "instructor_code": "INS1",
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
    }
    defaults.update(overrides)
    return defaults


def register_payload(session_id, customer_id, **overrides) -> dict:
    defaults = {"session_id": session_id, "customer_id": customer_id}
    defaults.update(overrides)
    return defaults


def create_framing_order_payload(order_id, customer_id, width_in, height_in, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "customer_id": customer_id,
        "width_in": width_in,
        "height_in": height_in,
    }
    defaults.update(overrides)
    return defaults


def create_project_bundle_payload(customer_id, bom, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "name": _uniq("Bundle"), "bom": bom}
    defaults.update(overrides)
    return defaults


def create_special_order_payload(customer_id, product_id, quantity, **overrides) -> dict:
    defaults = {"customer_id": customer_id, "product_id": product_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults
