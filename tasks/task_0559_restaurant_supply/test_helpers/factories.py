"""Payload factories — one per entity, input fields only (PRD §3)."""
import itertools

_sku_counter = itertools.count(1)


def unique_sku(prefix: str = "SKU") -> str:
    return f"{prefix}-{next(_sku_counter)}"


def account_payload(**overrides) -> dict:
    defaults = {
        "business_name": "Test Bistro",
        "credit_terms": "NET_30",
        "credit_limit_cents": 100_000_000,
    }
    defaults.update(overrides)
    return defaults


def certificate_payload(**overrides) -> dict:
    defaults = {
        "cert_number": "TX-0001",
        "state_code": "TX",
        "expiry_date": "2027-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def product_payload(**overrides) -> dict:
    """A fully valid STOCK/PARCEL SMALLWARE product. Override any field per test."""
    defaults = {
        "sku": unique_sku(),
        "name": "Test Product",
        "category": "SMALLWARE",
        "taxable": True,
        "unit_price_cents": 500,
        "case_qty": 12,
        "case_price_cents": 5400,
        "pallet_case_qty": 10,
        "pallet_price_cents": 48000,
        "weight_lbs_per_unit": 1,
        "fulfillment_type": "STOCK",
        "freight_type": "PARCEL",
        "on_hand_qty": 100,
        "par_level": 50,
        "reorder_point": 5,
    }
    defaults.update(overrides)
    return defaults


def order_payload(account_id: str, **overrides) -> dict:
    defaults = {"account_id": account_id}
    defaults.update(overrides)
    return defaults


def order_line_payload(product_id: str, quantity: int, **overrides) -> dict:
    defaults = {"product_id": product_id, "quantity": quantity}
    defaults.update(overrides)
    return defaults


def shipment_payload(order_id: str, carrier: str = "UPS", **overrides) -> dict:
    defaults = {"order_id": order_id, "carrier": carrier}
    defaults.update(overrides)
    return defaults


def return_payload(reason: str = "Damaged in transit", **overrides) -> dict:
    defaults = {"reason": reason}
    defaults.update(overrides)
    return defaults


def return_line_payload(product_id: str, quantity: int, condition: str, **overrides) -> dict:
    defaults = {"product_id": product_id, "quantity": quantity, "condition": condition}
    defaults.update(overrides)
    return defaults


def dock_payload(name: str = "Dock 1", **overrides) -> dict:
    defaults = {"name": name}
    defaults.update(overrides)
    return defaults


def crew_payload(name: str = "Crew 1", **overrides) -> dict:
    defaults = {"name": name}
    defaults.update(overrides)
    return defaults


def appointment_payload(order_id: str, dock_id: str, window_start: str, window_end: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "dock_id": dock_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def install_job_payload(order_id: str, crew_id: str, window_start: str, window_end: str, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "crew_id": crew_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults
