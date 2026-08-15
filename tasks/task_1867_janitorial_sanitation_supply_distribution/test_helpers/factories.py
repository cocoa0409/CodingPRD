"""Payload factories — one per entity, input fields only.

Computed and system-managed fields are never placed into request payloads.
"""
from .constants import (
    DEFAULT_CREDIT_LIMIT_CENTS,
    DEFAULT_DELIVERY_DATE,
    DEFAULT_DELIVERY_DAY,
    DEFAULT_DISTANCE_MILES,
    DEFAULT_FUEL_INDEX,
    DEFAULT_GROUP_CODE,
    DEFAULT_SERVICE_ZONE,
)

_sku_counter = [0]


def _next_sku(prefix: str = "SKU") -> str:
    _sku_counter[0] += 1
    return f"{prefix}-{_sku_counter[0]:04d}"


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Test Facility",
        "facility_group_code": DEFAULT_GROUP_CODE,
        "credit_limit_cents": DEFAULT_CREDIT_LIMIT_CENTS,
        "service_zone": DEFAULT_SERVICE_ZONE,
        "delivery_distance_miles": DEFAULT_DISTANCE_MILES,
        "default_delivery_day": DEFAULT_DELIVERY_DAY,
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _next_sku(),
        "name": "Test Product",
        "category": "PAPER",
        "base_price_cents": 1000,
        "unit_of_measure": "CASE",
        "dilution_required": False,
        "chemical_family": "NONE",
        "qty_on_hand": 100,
    }
    defaults.update(overrides)
    return defaults


def create_usage_record_payload(facility_id, product_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "product_id": product_id,
        "period_start": "2026-06-01T00:00:00Z",
        "period_end": "2026-06-30T00:00:00Z",
        "quantity_used": 90,
        "source": "MANUAL",
    }
    defaults.update(overrides)
    return defaults


def create_forecast_profile_payload(facility_id, product_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "product_id": product_id,
        "horizon_days": 30,
        "safety_stock": 0,
        "current_on_hand": 0,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {"name": "Tech One"}
    defaults.update(overrides)
    return defaults


def create_dispenser_payload(facility_id, product_id, technician_id,
                             **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "product_id": product_id,
        "zone": "kitchen",
        "technician_id": technician_id,
        "install_start": "2026-08-10T09:00:00Z",
        "install_end": "2026-08-10T10:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_training_record_payload(facility_id, product_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "product_id": product_id,
        "employee_name": "Emp One",
    }
    defaults.update(overrides)
    return defaults


def order_line(product_id, qty, discount_pct=None) -> dict:
    line = {"product_id": product_id, "qty": qty}
    if discount_pct is not None:
        line["discount_pct"] = discount_pct
    return line


def create_order_payload(facility_id, lines, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "lines": lines,
        "delivery_date": DEFAULT_DELIVERY_DATE,
        "fuel_index": DEFAULT_FUEL_INDEX,
    }
    defaults.update(overrides)
    return defaults


def create_standing_order_payload(facility_id, items, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "items": items,
        "frequency": "WEEKLY",
        "next_run_date": "2026-08-03T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_contract_bid_payload(facility_group_code, lines, **overrides) -> dict:
    defaults = {
        "bid_reference": _next_sku("BID"),
        "facility_group_code": facility_group_code,
        "lines": lines,
        "protection_start": "2026-07-01T00:00:00Z",
        "protection_end": "2026-12-31T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_trial_program_payload(facility_id, product_id, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "product_id": product_id,
        "trial_start": "2026-08-01T00:00:00Z",
        "trial_end": "2026-08-15T00:00:00Z",
        "sample_value_cents": 1000,
    }
    defaults.update(overrides)
    return defaults
