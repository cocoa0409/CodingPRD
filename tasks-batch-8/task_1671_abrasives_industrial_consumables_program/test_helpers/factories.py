"""Payload factories — one per entity, input fields only (PRD §3)."""
from typing import Any, Dict, List, Optional

DEFAULTS: Dict[str, Any] = {
    "SKU": "SKU-1",
    "PRODUCT_NAME": "Abrasive Product",
    "PRODUCT_FORM": "COATED",
    "MAX_RPM": 6000,
    "CUSTOMER_REF": "PLANT-1",
    "ASSET_TAG": "GR-01",
    "MACHINE_TYPE": "ANGLE_GRINDER",
    "SPINDLE_RPM": 5000,
    "GUARD_TYPE": "FIXED",
    "LOT_CODE": "L-1",
    "MANUFACTURE_DATE": "2026-06-01",
    "QTY_RECEIVED": 100,
    "OPERATION_NAME": "DEBURR",
    "STANDARD_QTY_PER_PART": 0.0250,
    "EFFECTIVE_FROM": "2026-01-01",
    "USAGE_DATE": "2026-08-01",
    "QTY_USED": 10,
    "PARTS_PRODUCED": 400,
    "CONTRACT_NUMBER": "C-1",
    "TERM_START": "2026-01-01",
    "TERM_END": "2027-12-31",
    "PRICE_HOLD_END": "2026-12-31",
    "ESCALATION_PCT": 0.0,
    "ESCALATION_EFFECTIVE_DATE": "2027-01-01",
    "BASE_PRICE_CENTS": 10000,
    "COMMITTED_QTY": 100,
    "RELEASE_QTY": 10,
    "SHIP_DATE": "2026-09-01",
    "TRIAL_START": "2026-09-01",
    "TRIAL_END": "2026-09-03",
    "REMOVAL_RATE": 12.5,
    "PARTS_PER_UNIT_MEDIA": 120,
    "COST_PER_PART_CENTS": 42,
    "QTY_DISPOSED": 10,
    "GROSS_WEIGHT_KG": 10.00,
    "DISPOSAL_METHOD": "HAZARDOUS_WASTE_FACILITY",
    "DISPOSED_AT": "2026-08-05",
    "CLOCK_DEFAULT": "2026-08-01T00:00:00Z",
}


def create_product_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "sku": DEFAULTS["SKU"],
        "name": DEFAULTS["PRODUCT_NAME"],
        "product_form": DEFAULTS["PRODUCT_FORM"],
        "max_operating_speed_rpm": DEFAULTS["MAX_RPM"],
    }
    payload.update(overrides)
    return payload


def create_machine_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "customer_ref": DEFAULTS["CUSTOMER_REF"],
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "machine_type": DEFAULTS["MACHINE_TYPE"],
        "spindle_max_rpm": DEFAULTS["SPINDLE_RPM"],
        "guard_type": DEFAULTS["GUARD_TYPE"],
    }
    payload.update(overrides)
    return payload


def create_lot_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "lot_code": DEFAULTS["LOT_CODE"],
        "manufacture_date": DEFAULTS["MANUFACTURE_DATE"],
        "qty_received": DEFAULTS["QTY_RECEIVED"],
    }
    payload.update(overrides)
    return payload


def create_standard_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "operation_name": DEFAULTS["OPERATION_NAME"],
        "standard_qty_per_part": DEFAULTS["STANDARD_QTY_PER_PART"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
    }
    payload.update(overrides)
    return payload


def create_usage_record_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "usage_date": DEFAULTS["USAGE_DATE"],
        "qty_used": DEFAULTS["QTY_USED"],
        "parts_produced": DEFAULTS["PARTS_PRODUCED"],
    }
    payload.update(overrides)
    return payload


def create_contract_payload(
    product_lines: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> dict:
    """product_lines: list of {product_id, base_unit_price_cents}."""
    payload: Dict[str, Any] = {
        "customer_ref": DEFAULTS["CUSTOMER_REF"],
        "contract_number": DEFAULTS["CONTRACT_NUMBER"],
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
        "price_hold_end": DEFAULTS["PRICE_HOLD_END"],
        "escalation_pct": DEFAULTS["ESCALATION_PCT"],
        "escalation_effective_date": DEFAULTS["ESCALATION_EFFECTIVE_DATE"],
        "lines": product_lines or [],
    }
    payload.update(overrides)
    return payload


def create_blanket_order_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "committed_qty": DEFAULTS["COMMITTED_QTY"],
    }
    payload.update(overrides)
    return payload


def create_release_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "qty": DEFAULTS["RELEASE_QTY"],
        "scheduled_ship_date": DEFAULTS["SHIP_DATE"],
    }
    payload.update(overrides)
    return payload


def create_trial_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "scheduled_start": DEFAULTS["TRIAL_START"],
        "scheduled_end": DEFAULTS["TRIAL_END"],
    }
    payload.update(overrides)
    return payload


def submit_results_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "measured_removal_rate_g_per_min": DEFAULTS["REMOVAL_RATE"],
        "parts_per_unit_media": DEFAULTS["PARTS_PER_UNIT_MEDIA"],
        "cost_per_part_cents": DEFAULTS["COST_PER_PART_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_disposal_record_payload(**overrides: Any) -> dict:
    payload: Dict[str, Any] = {
        "customer_ref": DEFAULTS["CUSTOMER_REF"],
        "qty_disposed": DEFAULTS["QTY_DISPOSED"],
        "gross_weight_kg": DEFAULTS["GROSS_WEIGHT_KG"],
        "disposal_method": DEFAULTS["DISPOSAL_METHOD"],
        "disposed_at": DEFAULTS["DISPOSED_AT"],
    }
    payload.update(overrides)
    return payload
