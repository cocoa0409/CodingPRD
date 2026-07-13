"""Payload factories — one per entity, input fields only."""
from .constants import (
    DEFAULT_IN_HANDS_ISO,
    DEFAULT_INITIAL_CREDIT_CENTS,
    DEFAULT_BLANK_UNIT_COST_CENTS,
    DEFAULT_CONCURRENT_CAPACITY_UNITS,
    DEFAULT_CLOCK_ISO,
)


def create_supplier_payload(**overrides) -> dict:
    payload = {
        "name": "BlankCo",
        "blank_unit_cost_cents": DEFAULT_BLANK_UNIT_COST_CENTS,
        "concurrent_capacity_units": DEFAULT_CONCURRENT_CAPACITY_UNITS,
    }
    payload.update(overrides)
    return payload


def create_product_payload(supplier_id, **overrides) -> dict:
    payload = {
        "supplier_id": supplier_id,
        "sku": "TOTE",
        "name": "Cotton Tote",
        "min_order_qty": 48,
    }
    payload.update(overrides)
    return payload


def create_price_tier_payload(**overrides) -> dict:
    payload = {
        "decoration_method": "SCREEN_PRINT",
        "min_quantity": 48,
        "unit_price_cents": 599,
    }
    payload.update(overrides)
    return payload


def create_station_payload(**overrides) -> dict:
    payload = {"name": "Press1", "station_type": "SCREEN_PRESS"}
    payload.update(overrides)
    return payload


def create_customer_payload(**overrides) -> dict:
    payload = {"name": "Acme", "initial_credit_cents": DEFAULT_INITIAL_CREDIT_CENTS}
    payload.update(overrides)
    return payload


def create_order_payload(customer_id, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "order_type": "STANDARD",
        "in_hands_date": DEFAULT_IN_HANDS_ISO,
    }
    payload.update(overrides)
    return payload


def create_line_payload(product_id, **overrides) -> dict:
    payload = {
        "product_id": product_id,
        "decoration_method": "SCREEN_PRINT",
        "quantity": 200,
        "imprint_color_count": 1,
    }
    payload.update(overrides)
    return payload


def create_art_proof_payload(expected_order_line_version, **overrides) -> dict:
    payload = {
        "proof_url": "http://x/a.png",
        "expected_order_line_version": expected_order_line_version,
    }
    payload.update(overrides)
    return payload


def create_purchase_order_payload(order_line_id, supplier_id, **overrides) -> dict:
    payload = {
        "order_line_id": order_line_id,
        "supplier_id": supplier_id,
        "ordered_blank_qty": 210,
        "production_start": "2026-05-05T00:00:00Z",
        "production_end": "2026-05-08T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_payment_payload(amount_cents, **overrides) -> dict:
    payload = {"amount_cents": amount_cents}
    payload.update(overrides)
    return payload


def create_shipment_payload(order_id, **overrides) -> dict:
    payload = {"order_id": order_id, "carrier": "UPS"}
    payload.update(overrides)
    return payload


def schedule_payload(station_id, scheduled_start, scheduled_end, **overrides) -> dict:
    payload = {
        "station_id": station_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
    }
    payload.update(overrides)
    return payload


def complete_run_payload(produced_qty, spoiled_qty, **overrides) -> dict:
    payload = {"produced_qty": produced_qty, "spoiled_qty": spoiled_qty}
    payload.update(overrides)
    return payload


def qc_payload(result, **overrides) -> dict:
    payload = {"result": result}
    payload.update(overrides)
    return payload


def receive_payload(received_blank_qty, **overrides) -> dict:
    payload = {"received_blank_qty": received_blank_qty}
    payload.update(overrides)
    return payload


def reorder_payload(in_hands_date=DEFAULT_IN_HANDS_ISO, **overrides) -> dict:
    payload = {"in_hands_date": in_hands_date}
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601=DEFAULT_CLOCK_ISO, **overrides) -> dict:
    payload = {"to_iso8601": to_iso8601}
    payload.update(overrides)
    return payload
