"""Payload factories — one per creatable resource, input fields only (PRD §3)."""

from .constants import (
    DEFAULT_QUARTER,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
    TEST_DEFAULTS,
)

_CLINIC_SEQ = {"n": 0}
_PRODUCT_SEQ = {"n": 0}
_LOT_SEQ = {"n": 0}
_PROGRAM_SEQ = {"n": 0}


def _next(seq: dict) -> int:
    seq["n"] += 1
    return seq["n"]


def create_clinic_payload(**overrides) -> dict:
    n = _next(_CLINIC_SEQ)
    defaults = {
        "clinic_name": f"Test Clinic {n}",
        "license_number": f"LIC-{n:04d}",
        "ship_to_address": f"{n} Clinic Way",
        "credit_limit_cents": TEST_DEFAULTS["CLINIC_CREDIT_LIMIT_CENTS"],
        "minimum_order_value_cents": TEST_DEFAULTS["CLINIC_MINIMUM_ORDER_CENTS"],
        "delivery_frequency_per_week": TEST_DEFAULTS["CLINIC_DELIVERY_FREQUENCY_PER_WEEK"],
        "free_freight_threshold_cents": TEST_DEFAULTS["CLINIC_FREE_FREIGHT_THRESHOLD_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    n = _next(_PRODUCT_SEQ)
    defaults = {
        "sku": f"SKU-{n:04d}",
        "product_name": f"Test Product {n}",
        "manufacturer_code": "GEN",
        "product_type": "CONSUMABLE",
        "unit_price_cents": TEST_DEFAULTS["UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(product_id, **overrides) -> dict:
    n = _next(_LOT_SEQ)
    defaults = {
        "product_id": product_id,
        "lot_number": f"LOT-{n:04d}",
        "expiry_date": TEST_DEFAULTS["LOT_EXPIRY_DATE"],
        "qty_on_hand": TEST_DEFAULTS["LOT_QTY_ON_HAND"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(clinic_id, lines, **overrides) -> dict:
    defaults = {
        "clinic_id": clinic_id,
        "ship_to_address": None,  # caller fills from the clinic record
        "delivery_window_start": DEFAULT_WINDOW_START,
        "delivery_window_end": DEFAULT_WINDOW_END,
        "lines": lines,
    }
    defaults.update(overrides)
    return defaults


def order_line_spec(product_id, qty_requested) -> dict:
    return {"product_id": product_id, "qty_requested": qty_requested}


def create_authorization_payload(clinic_id, **overrides) -> dict:
    defaults = {
        "clinic_id": clinic_id,
        "manufacturer_code": "ZOETIS",
        "valid_from": "2026-01-01",
        "valid_until": "2026-12-31",
        "approved_ship_to_address": None,  # caller fills from the clinic record
        "quarterly_quantity_cap": TEST_DEFAULTS["AUTH_QUARTERLY_QUANTITY_CAP"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(order_id, **overrides) -> dict:
    defaults = {
        "order_id": order_id,
        "carrier_name": "VETEXPRESS",
    }
    defaults.update(overrides)
    return defaults


def temperature_reading_payload(temperature_celsius,
                                recorded_at="2026-08-03T14:00:00Z") -> dict:
    return {"recorded_at": recorded_at, "temperature_celsius": temperature_celsius}


def create_bundle_program_payload(**overrides) -> dict:
    n = _next(_PROGRAM_SEQ)
    defaults = {
        "program_name": f"Program {n}",
        "manufacturer_code": "ACME-VET",
        "qualifying_product_types": ["CONSUMABLE"],
        "min_distinct_categories": 1,
        "bundle_discount_pct": 0,
        "rebate_base_rate_bp": 200,
        "rebate_bonus_rate_bp": 500,
        "bonus_threshold_cents": 1000000,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(program_id, expected_clinic_version,
                              quarter=DEFAULT_QUARTER) -> dict:
    return {
        "program_id": program_id,
        "quarter": quarter,
        "expected_clinic_version": expected_clinic_version,
    }


def create_short_date_credit_payload(order_line_id, lot_id, qty) -> dict:
    return {"order_line_id": order_line_id, "lot_id": lot_id, "qty": qty}
