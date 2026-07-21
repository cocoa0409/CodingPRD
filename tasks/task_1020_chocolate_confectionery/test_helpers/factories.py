"""Payload factories — one per entity, input fields only (PRD Section 3)."""
import uuid


def _suffix() -> str:
    return uuid.uuid4().hex[:8]


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Customer",
        "email": f"cust-{_suffix()}@example.com",
        "account_type": "RETAIL",
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": f"SKU-{_suffix()}",
        "name": "Test Product",
        "product_type": "SINGLE",
        "base_price_cents": 1000,
        "shelf_life_days": 30,
        "unit_weight_g": 20,
    }
    defaults.update(overrides)
    return defaults


def bundle_component_payload(component_product_id: str, quantity: int, **overrides) -> dict:
    defaults = {"component_product_id": component_product_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_mold_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Mold",
        "cavity_count": 8,
        "daily_capacity_units": 300,
    }
    defaults.update(overrides)
    return defaults


def create_tempering_line_payload(**overrides) -> dict:
    defaults = {"name": "Test Line"}
    defaults.update(overrides)
    return defaults


def create_batch_payload(product_id: str, initial_units: int, **overrides) -> dict:
    defaults = {"product_id": product_id, "initial_units": initial_units}
    defaults.update(overrides)
    return defaults


def start_tempering_payload(tempering_line_id: str, temper_start: str, **overrides) -> dict:
    defaults = {"tempering_line_id": tempering_line_id, "temper_start": temper_start}
    defaults.update(overrides)
    return defaults


def create_reservation_payload(order_line_id: str, units: int, expected_batch_version: int, **overrides) -> dict:
    defaults = {
        "order_line_id": order_line_id,
        "units": units,
        "expected_batch_version": expected_batch_version,
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(customer_id: str, order_type: str = "RETAIL", **overrides) -> dict:
    defaults = {"customer_id": customer_id, "order_type": order_type}
    defaults.update(overrides)
    return defaults


def order_line_payload(product_id: str, quantity: int, **overrides) -> dict:
    defaults = {"product_id": product_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def create_custom_order_payload(customer_id: str, product_id: str, mold_id: str, units_estimated: int, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_id": product_id,
        "mold_id": mold_id,
        "units_estimated": units_estimated,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(customer_id: str, box_product_id: str, cadence_days: int, next_ship_date: str, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "box_product_id": box_product_id,
        "cadence_days": cadence_days,
        "next_ship_date": next_ship_date,
    }
    defaults.update(overrides)
    return defaults


def wallet_adjust_payload(amount_cents: int) -> dict:
    return {"amount_cents": amount_cents}


def set_clock_payload(to_iso8601: str) -> dict:
    return {"to_iso8601": to_iso8601}
