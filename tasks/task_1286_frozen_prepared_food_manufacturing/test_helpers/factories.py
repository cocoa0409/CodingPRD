"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "RECIPE_NAME": "Test Recipe",
    "PRODUCT_STYLE": "ENTREE",
    "BASE_BATCH_YIELD_UNITS": 1000,
    "PORTION_WEIGHT_G": 340,
    "SHELF_LIFE_DAYS": 365,
    "COMPONENT_NAME": "Sauce",
    "COMPONENT_TYPE": "RAW_INGREDIENT",
    "QTY_PER_BASE_BATCH": 50,
    "UNIT_OF_MEASURE": "KG",
    "CUSTOMER_NAME": "Test Customer",
    "BILLING_METHOD": "PER_CASE",
    "CASE_RATE_CENTS": 1500,
    "KG_RATE_CENTS": 120,
    "PACK_FORMAT": "RETAIL",
    "UNITS_PLANNED": 6000,
    "BATCH_UNITS": 6000,
    "COOKED_MASS_KG": 1550,
    "CELL_CODE": "FC-1",
    "CAPACITY_KG": 2000,
    "MIN_LOAD_KG": 200,
    "PULL_DOWN_KG_PER_HOUR": 400,
    "SANITATION_MINUTES": 30,
    "LOAD_KG": 1600,
    "ENTRY_TEMP_C": 5,
    "PLANNED_START": "2026-08-02T00:00:00Z",
    "ACTUAL_END": "2026-08-02T05:00:00Z",
    "FINAL_CORE_TEMP_C": -20,
    "LINE_CODE": "L-1",
    "LINE_TYPE": "TRAY",
    "RATE_UNITS_PER_MINUTE": 100,
    "SUPPORTED_FILM_TYPE": "TRAY_FILM",
    "FILM_TYPE": "TRAY_FILM",
    "ROLLS_RECEIVED": 10,
    "METERS_PER_ROLL": 1000,
    "RUN_PLANNED_START": "2026-08-03T08:00:00Z",
    "FILM_METERS_CONSUMED": 2671,
    "SLOT_CODE": "S-1",
    "ZONE": "FREEZER_A",
    "TEMPERATURE_CLASS": "STANDARD",
    "CAPACITY_CASES": 600,
    "COMPLAINT_TYPE": "FREEZER_BURN",
    "UNITS_AFFECTED": 1,
}


def create_recipe_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RECIPE_NAME"],
        "product_style": DEFAULTS["PRODUCT_STYLE"],
        "base_batch_yield_units": DEFAULTS["BASE_BATCH_YIELD_UNITS"],
        "portion_weight_g": DEFAULTS["PORTION_WEIGHT_G"],
        "shelf_life_days": DEFAULTS["SHELF_LIFE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_component_payload(**overrides) -> dict:
    defaults = {
        "component_name": DEFAULTS["COMPONENT_NAME"],
        "component_type": DEFAULTS["COMPONENT_TYPE"],
        "quantity_per_base_batch": DEFAULTS["QTY_PER_BASE_BATCH"],
        "unit_of_measure": DEFAULTS["UNIT_OF_MEASURE"],
    }
    defaults.update(overrides)
    return defaults


def create_copack_customer_payload(**overrides) -> dict:
    """Customer payload honoring PRD §3.2 rate-field conditionality:
    `case_rate_cents` exactly when PER_CASE, `kg_rate_cents` exactly when
    PER_KG, the other null/absent."""
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "billing_method": DEFAULTS["BILLING_METHOD"],
        "case_rate_cents": DEFAULTS["CASE_RATE_CENTS"],
    }
    defaults.update(overrides)
    if defaults.get("billing_method") == "PER_KG":
        defaults.pop("case_rate_cents", None)
        defaults.setdefault("kg_rate_cents", DEFAULTS["KG_RATE_CENTS"])
    return defaults


def create_order_payload(recipe_id, **overrides) -> dict:
    defaults = {
        "recipe_id": recipe_id,
        "pack_format": DEFAULTS["PACK_FORMAT"],
        "units_planned": DEFAULTS["UNITS_PLANNED"],
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(expected_order_version, **overrides) -> dict:
    defaults = {
        "units_planned": DEFAULTS["BATCH_UNITS"],
        "expected_order_version": expected_order_version,
    }
    defaults.update(overrides)
    return defaults


def cook_batch_payload(**overrides) -> dict:
    defaults = {"cooked_mass_kg": DEFAULTS["COOKED_MASS_KG"]}
    defaults.update(overrides)
    return defaults


def create_freezer_cell_payload(**overrides) -> dict:
    defaults = {
        "cell_code": DEFAULTS["CELL_CODE"],
        "capacity_kg": DEFAULTS["CAPACITY_KG"],
        "min_load_kg": DEFAULTS["MIN_LOAD_KG"],
        "pull_down_kg_per_hour": DEFAULTS["PULL_DOWN_KG_PER_HOUR"],
        "sanitation_minutes": DEFAULTS["SANITATION_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(expected_batch_version, **overrides) -> dict:
    defaults = {
        "load_kg": DEFAULTS["LOAD_KG"],
        "entry_temp_c": DEFAULTS["ENTRY_TEMP_C"],
        "planned_start": DEFAULTS["PLANNED_START"],
        "expected_batch_version": expected_batch_version,
    }
    defaults.update(overrides)
    return defaults


def complete_cycle_payload(**overrides) -> dict:
    defaults = {
        "actual_end": DEFAULTS["ACTUAL_END"],
        "final_core_temp_c": DEFAULTS["FINAL_CORE_TEMP_C"],
    }
    defaults.update(overrides)
    return defaults


def create_packaging_line_payload(**overrides) -> dict:
    defaults = {
        "line_code": DEFAULTS["LINE_CODE"],
        "line_type": DEFAULTS["LINE_TYPE"],
        "rate_units_per_minute": DEFAULTS["RATE_UNITS_PER_MINUTE"],
        "supported_film_type": DEFAULTS["SUPPORTED_FILM_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_film_lot_payload(**overrides) -> dict:
    defaults = {
        "film_type": DEFAULTS["FILM_TYPE"],
        "rolls_received": DEFAULTS["ROLLS_RECEIVED"],
        "meters_per_roll": DEFAULTS["METERS_PER_ROLL"],
    }
    defaults.update(overrides)
    return defaults


def create_line_run_payload(batch_id, film_lot_id, **overrides) -> dict:
    defaults = {
        "batch_id": batch_id,
        "film_lot_id": film_lot_id,
        "planned_start": DEFAULTS["RUN_PLANNED_START"],
        "units_planned": DEFAULTS["UNITS_PLANNED"],
    }
    defaults.update(overrides)
    return defaults


def complete_run_payload(**overrides) -> dict:
    defaults = {
        "units_packed": DEFAULTS["UNITS_PLANNED"],
        "film_meters_consumed": DEFAULTS["FILM_METERS_CONSUMED"],
    }
    defaults.update(overrides)
    return defaults


def create_storage_slot_payload(**overrides) -> dict:
    defaults = {
        "slot_code": DEFAULTS["SLOT_CODE"],
        "zone": DEFAULTS["ZONE"],
        "temperature_class": DEFAULTS["TEMPERATURE_CLASS"],
        "capacity_cases": DEFAULTS["CAPACITY_CASES"],
    }
    defaults.update(overrides)
    return defaults


def ccp_check_payload(**overrides) -> dict:
    defaults = {
        "check_type": "METAL_DETECTOR",
        "test_piece_detected": True,
    }
    defaults.update(overrides)
    return defaults


def put_away_payload(slot_id, cases, **overrides) -> dict:
    defaults = {"slot_id": slot_id, "cases": cases}
    defaults.update(overrides)
    return defaults


def withdraw_payload(cases, purpose="SHIPMENT", **overrides) -> dict:
    defaults = {"cases": cases, "purpose": purpose}
    defaults.update(overrides)
    return defaults


def create_complaint_payload(lot_id, **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "complaint_type": DEFAULTS["COMPLAINT_TYPE"],
        "units_affected": DEFAULTS["UNITS_AFFECTED"],
    }
    defaults.update(overrides)
    return defaults
