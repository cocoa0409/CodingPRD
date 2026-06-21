"""Payload factories — one per write endpoint, input fields only.

Each factory provides sensible defaults and merges **overrides last so any test
can pin a specific field. FK fields that have no sensible default (facility_id,
ingredient_id, lot_id, etc.) are required positional/keyword arguments.
"""

DEFAULTS = {
    "FACILITY_NAME": "Test Facility",
    "INITIAL_UTC": "2026-01-01T00:00:00Z",
    "SUPPLIER_NAME": "Test Supplier",
    "INGREDIENT_NAME": "Test Ingredient",
    "STORAGE_TARGET_C": 4,
    "STORAGE_TOLERANCE_C": 2,
    "SHELF_LIFE_DAYS": 30,
    "PRODUCTION_DATE": "2026-01-01T00:00:00Z",
}

_GLN_COUNTER = {"n": 0}


def _next_gln() -> str:
    _GLN_COUNTER["n"] += 1
    return f"GLN-{_GLN_COUNTER['n']:06d}"


def create_facility_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FACILITY_NAME"],
        "gln": _next_gln(),
        "initial_utc": DEFAULTS["INITIAL_UTC"],
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "name": DEFAULTS["SUPPLIER_NAME"],
        "coa_required": False,
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_payload(facility_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "name": DEFAULTS["INGREDIENT_NAME"],
        "storage_target_c": DEFAULTS["STORAGE_TARGET_C"],
        "storage_tolerance_c": DEFAULTS["STORAGE_TOLERANCE_C"],
        "shelf_life_days": DEFAULTS["SHELF_LIFE_DAYS"],
        "declared_allergen_codes": [],
    }
    defaults.update(overrides)
    return defaults


def create_allergen_profile_payload(facility_id: str, code: str, severity_rank: int, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "code": code,
        "name": code.title(),
        "severity_rank": severity_rank,
    }
    defaults.update(overrides)
    return defaults


def create_lot_payload(facility_id: str, ingredient_id: str, lot_code: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "ingredient_id": ingredient_id,
        "lot_code": lot_code,
        "lot_kind": "RAW_MATERIAL",
        "received_qty": 100,
        "production_date": DEFAULTS["PRODUCTION_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_coa_payload(lot_id: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "measured_allergen_codes": [],
        "pathogen_pass": True,
        "declared_shelf_life_days": 30,
    }
    defaults.update(overrides)
    return defaults


def decide_coa_payload(decision: str) -> dict:
    return {"decision": decision}


def create_production_run_payload(facility_id: str, ingredient_id: str, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "ingredient_id": ingredient_id,
        "planned_output_qty": 10,
    }
    defaults.update(overrides)
    return defaults


def create_consumed_lot_payload(source_lot_id: str, quantity: float, **overrides) -> dict:
    defaults = {
        "source_lot_id": source_lot_id,
        "quantity": quantity,
    }
    defaults.update(overrides)
    return defaults


def finalize_payload(expected_production_run_version: int) -> dict:
    return {"expected_production_run_version": expected_production_run_version}


def create_ccp_reading_payload(lot_id: str, measured_value_c: float, measured_at: str, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "ccp_type": "TEMPERATURE",
        "measured_value_c": measured_value_c,
        "measured_at": measured_at,
    }
    defaults.update(overrides)
    return defaults


def create_hold_order_payload(facility_id: str, target_lot_id: str, reason: str = "OTHER", **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "target_lot_id": target_lot_id,
        "reason": reason,
    }
    defaults.update(overrides)
    return defaults


def resolve_hold_payload(disposition: str, expected_hold_order_version: int) -> dict:
    return {
        "disposition": disposition,
        "expected_hold_order_version": expected_hold_order_version,
    }


def create_zone_payload(facility_id: str, zone_code: str, capacity_units: float, **overrides) -> dict:
    defaults = {
        "facility_id": facility_id,
        "zone_code": zone_code,
        "capacity_units": capacity_units,
        "target_temp_c": 2,
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(lot_id: str, start_utc: str, end_utc: str, capacity_units: float, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "capacity_units": capacity_units,
    }
    defaults.update(overrides)
    return defaults


def advance_clock_payload(to_utc: str) -> dict:
    return {"to_utc": to_utc}
