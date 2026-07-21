"""Payload factories — one per entity, input fields only."""
import uuid


def _unique_email(prefix: str = "member") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


def create_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Test Member",
        "email": _unique_email(),
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Product",
        "kind": "GAME",
        "base_price_cents": 6000,
        "base_trade_value_cents": 3000,
    }
    defaults.update(overrides)
    return defaults


def create_product_stock_payload(**overrides) -> dict:
    defaults = {
        "unit_price_cents": 6000,
        "deposit_cents": 2000,
        "total_count": 1,
    }
    defaults.update(overrides)
    return defaults


def create_inventory_item_payload(**overrides) -> dict:
    defaults = {
        "condition_grade": "A",
    }
    defaults.update(overrides)
    return defaults


def create_pre_order_payload(member_id: str, product_stock_id: str,
                             expected_product_stock_version: int, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "product_stock_id": product_stock_id,
        "expected_product_stock_version": expected_product_stock_version,
    }
    defaults.update(overrides)
    return defaults


def create_trade_in_payload(member_id: str, product_id: str,
                            stated_grade: str = "A",
                            payout_method: str = "STORE_CREDIT", **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "product_id": product_id,
        "stated_grade": stated_grade,
        "payout_method": payout_method,
    }
    defaults.update(overrides)
    return defaults


def create_rental_payload(member_id: str, inventory_item_id: str,
                          start_at: str, due_at: str, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "inventory_item_id": inventory_item_id,
        "start_at": start_at,
        "due_at": due_at,
    }
    defaults.update(overrides)
    return defaults


def create_sale_payload(member_id: str, lines: list, **overrides) -> dict:
    defaults = {
        "member_id": member_id,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def sale_line(inventory_item_id: str, unit_price_cents: int, qty: int = 1) -> dict:
    return {
        "inventory_item_id": inventory_item_id,
        "unit_price_cents": unit_price_cents,
        "qty": qty,
    }


def create_station_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Station",
        "seat_capacity": 8,
    }
    defaults.update(overrides)
    return defaults


def create_tournament_payload(station_id: str, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "title": "Test Cup",
        "starts_at": "2026-07-05T10:00:00Z",
        "ends_at": "2026-07-05T12:00:00Z",
        "registration_opens_at": "2026-07-01T00:00:00Z",
        "registration_closes_at": "2026-07-05T09:00:00Z",
        "max_participants": 8,
    }
    defaults.update(overrides)
    return defaults


def payment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def adjustment_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def grade_payload(final_grade: str) -> dict:
    return {"final_grade": final_grade}


def register_payload(member_id: str) -> dict:
    return {"member_id": member_id}


def clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
