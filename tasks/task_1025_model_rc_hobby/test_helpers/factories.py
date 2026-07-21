"""Payload factories — one per entity, input fields only."""
import uuid

from .constants import OPEN_WINDOW_START, OPEN_WINDOW_END


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def create_customer_payload(**overrides) -> dict:
    payload = {
        "email": _uniq("member") + "@example.com",
        "full_name": "Test Member",
    }
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    payload = {
        "sku": _uniq("SKU"),
        "name": "Test Product",
        "product_type": "KIT",
        "price_cents": 10000,
        "stock_on_hand": 10,
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(**overrides) -> dict:
    payload = {
        "product_id": None,
        "title": "Test Campaign",
        "total_allocation_units": 10,
        "unit_price_cents": 10000,
        "reservation_open_at": OPEN_WINDOW_START,
        "reservation_close_at": OPEN_WINDOW_END,
    }
    payload.update(overrides)
    return payload


def create_reservation_payload(**overrides) -> dict:
    payload = {
        "customer_id": None,
        "requested_units": 1,
        "expected_campaign_version": 1,
    }
    payload.update(overrides)
    return payload


def order_line(product_id, quantity=1, unit_price_cents=10000) -> dict:
    return {
        "product_id": product_id,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
    }


def create_order_payload(**overrides) -> dict:
    payload = {
        "customer_id": None,
        "lines": [],
    }
    payload.update(overrides)
    return payload


def create_service_job_payload(**overrides) -> dict:
    payload = {
        "customer_id": None,
        "job_type": "REPAIR",
    }
    payload.update(overrides)
    return payload


def create_race_event_payload(**overrides) -> dict:
    payload = {
        "name": "Test Race",
        "event_date": "2026-07-15T10:00:00Z",
        "capacity": 8,
        "lane_count": 4,
        "entry_fee_cents": 1000,
        "registration_open_at": "2026-07-01T00:00:00Z",
        "registration_close_at": "2026-07-20T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_race_entry_payload(**overrides) -> dict:
    payload = {
        "customer_id": None,
        "race_class": "STOCK",
        "lane_no": 1,
        "heat_start": "2026-07-15T10:00:00Z",
        "heat_end": "2026-07-15T10:10:00Z",
    }
    payload.update(overrides)
    return payload
