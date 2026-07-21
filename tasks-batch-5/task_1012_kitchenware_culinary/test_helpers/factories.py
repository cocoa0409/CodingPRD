"""Payload factories — one per entity, input fields only.

Only fields the client supplies (source: input) appear here. Server-managed
and computed fields (ids, versions, statuses, totals, points, reserved_qty,
etc.) are never supplied.
"""
import uuid


def _unique_email(prefix: str = "member") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def order_line(sku_id: str, qty: int, is_gift=None) -> dict:
    """Build a single order line input object. line_id / unit_price_cents /
    line_status are server-set and therefore omitted."""
    line = {"sku_id": sku_id, "qty": qty}
    if is_gift is not None:
        line["is_gift"] = is_gift
    return line


def create_store_payload(**overrides) -> dict:
    defaults = {"name": "Test Store", "state_code": "OR"}
    defaults.update(overrides)
    return defaults


def create_sku_payload(**overrides) -> dict:
    defaults = {
        "name": "Test SKU",
        "category": "COOKWARE",
        "list_price_cents": 10000,
        "on_hand_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_member_payload(home_store_id: str, **overrides) -> dict:
    defaults = {
        "email": _unique_email(),
        "full_name": "Test Member",
        "home_store_id": home_store_id,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(member_id: str, store_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "store_id": store_id,
        "fulfillment_type": "BOPIS",
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def create_cooking_class_payload(store_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "title": "Test Class",
        "station": "DEMO_KITCHEN",
        "start_at": "2026-07-20T10:00:00Z",
        "end_at": "2026-07-20T12:00:00Z",
        "capacity": 6,
        "price_cents": 5000,
    }
    defaults.update(overrides)
    return defaults


def create_class_registration_payload(class_id: str, member_id: str, **overrides) -> dict:
    defaults = {"class_id": class_id, "member_id": member_id}
    defaults.update(overrides)
    return defaults


def create_service_ticket_payload(store_id: str, **overrides) -> dict:
    defaults = {
        "store_id": store_id,
        "service_type": "KNIFE_SHARPENING",
        "start_at": "2026-07-12T09:00:00Z",
        "end_at": "2026-07-12T09:30:00Z",
        "price_cents": 1500,
    }
    defaults.update(overrides)
    return defaults


def create_return_payload(order_id: str, member_id: str, line_id: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "member_id": member_id,
        "line_id": line_id,
        "return_qty": 1,
        "reason": "DEFECTIVE",
        "refund_destination": "WALLET",
    }
    defaults.update(overrides)
    return defaults


def create_special_order_payload(member_id: str, store_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "store_id": store_id,
        "description": "Custom item",
        "estimated_cost_cents": 40000,
    }
    defaults.update(overrides)
    return defaults


def create_registry_payload(member_id: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "event_type": "WEDDING",
        "event_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
