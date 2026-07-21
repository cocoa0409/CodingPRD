"""Payload factories — one per entity, input fields only.

Defaults are sensible baseline values; every factory accepts **overrides so a
test can pin exactly the field it exercises.
"""


def create_customer_payload(**overrides) -> dict:
    payload = {"email": "customer@example.com", "full_name": "Test Customer"}
    payload.update(overrides)
    return payload


def create_product_payload(**overrides) -> dict:
    payload = {"name": "Test Fragrance", "brand": "Maison Test", "concentration": "EDP"}
    payload.update(overrides)
    return payload


def create_variant_payload(**overrides) -> dict:
    payload = {
        "kind": "FULL_BOTTLE",
        "volume_ml": 100,
        "unit_price_cents": 10000,
        "on_hand_qty": 5,
    }
    payload.update(overrides)
    return payload


def create_order_payload(customer_id: str, **overrides) -> dict:
    payload = {"customer_id": customer_id}
    payload.update(overrides)
    return payload


def create_order_line_payload(variant_id: str, quantity: int = 1, **overrides) -> dict:
    payload = {"variant_id": variant_id, "quantity": quantity}
    payload.update(overrides)
    return payload


def create_subscription_payload(customer_id: str, **overrides) -> dict:
    payload = {"customer_id": customer_id, "tier": "BASIC", "monthly_fee_cents": 5000}
    payload.update(overrides)
    return payload


def create_shipment_payload(period_start: str, period_end: str, **overrides) -> dict:
    payload = {"period_start": period_start, "period_end": period_end}
    payload.update(overrides)
    return payload


def create_allocation_window_payload(
    window_start: str,
    window_end: str,
    total_allocation: int,
    per_customer_cap: int,
    **overrides,
) -> dict:
    payload = {
        "window_start": window_start,
        "window_end": window_end,
        "total_allocation": total_allocation,
        "per_customer_cap": per_customer_cap,
    }
    payload.update(overrides)
    return payload


def create_claim_payload(customer_id: str, units: int, expected_window_version: int, **overrides) -> dict:
    payload = {
        "customer_id": customer_id,
        "units": units,
        "expected_window_version": expected_window_version,
    }
    payload.update(overrides)
    return payload


def create_return_payload(order_id: str, line_ids: list, condition: str, **overrides) -> dict:
    payload = {"order_id": order_id, "line_ids": line_ids, "condition": condition}
    payload.update(overrides)
    return payload
