"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "BRAND_NAME": "Acme Foods",
    "CONTACT_EMAIL": "ops@acme.example",
    "CREDIT_LIMIT_CENTS": 100_000_000,
    "PRODUCT_NAME": "Ghost Pepper Sauce",
    "SKU_CODE": "GPS-001",
    "PROCESS_CATEGORY": "ACIDIFIED",
    "ALLERGEN_CLASS": "NONE",
    "MIN_RUN_UNITS": 1000,
    "UNIT_RATE_CENTS": 120,
    "CELL_NAME": "Pilot-1",
    "MAX_BATCH_UNITS": 5000,
    "LINE_NAME": "Kettle-1",
    "CAPACITY_UNITS": 100_000,
    "AUTHORITY_NAME": "Dr. Rosa Kim",
    "LETTER_NUMBER": "PAL-1001",
    "MAX_PH": 4.2,
    "MAX_WATER_ACTIVITY": 0.9,
    "BOTTLE_NAME": "12oz woozy bottle",
    "CAP_NAME": "38mm cap",
    "COMPONENT_INITIAL_ON_HAND": 100_000,
    "TRIAL_START": "2026-09-01T08:00:00Z",
    "TRIAL_END": "2026-09-01T12:00:00Z",
    "RUN_START": "2026-09-10T08:00:00Z",
    "RUN_END": "2026-09-10T16:00:00Z",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "brand_name": DEFAULTS["BRAND_NAME"],
        "contact_email": DEFAULTS["CONTACT_EMAIL"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_formula_payload(customer_id, **overrides) -> dict:
    defaults = {
        "customer_id": customer_id,
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "sku_code": DEFAULTS["SKU_CODE"],
        "process_category": DEFAULTS["PROCESS_CATEGORY"],
        "allergen_class": DEFAULTS["ALLERGEN_CLASS"],
        "min_run_units": DEFAULTS["MIN_RUN_UNITS"],
        "unit_rate_cents": DEFAULTS["UNIT_RATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_ingredient_supply_payload(formula_id, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "ingredient_name": "Ghost pepper mash",
        "sourcing_mode": "CUSTOMER_SUPPLIED",
        "quantity_per_unit": 0.5,
    }
    defaults.update(overrides)
    return defaults


def create_pilot_cell_payload(**overrides) -> dict:
    defaults = {
        "cell_name": DEFAULTS["CELL_NAME"],
        "max_batch_units": DEFAULTS["MAX_BATCH_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_scale_up_trial_payload(formula_id, pilot_cell_id, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "pilot_cell_id": pilot_cell_id,
        "batch_size_units": 500,
        "scheduled_start": DEFAULTS["TRIAL_START"],
        "scheduled_end": DEFAULTS["TRIAL_END"],
    }
    defaults.update(overrides)
    return defaults


def create_letter_payload(formula_id, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "formula_revision": 1,
        "authority_name": DEFAULTS["AUTHORITY_NAME"],
        "letter_number": DEFAULTS["LETTER_NUMBER"],
        "max_ph": DEFAULTS["MAX_PH"],
        "max_water_activity": DEFAULTS["MAX_WATER_ACTIVITY"],
    }
    defaults.update(overrides)
    return defaults


def create_kettle_line_payload(**overrides) -> dict:
    defaults = {
        "line_name": DEFAULTS["LINE_NAME"],
        "capacity_units": DEFAULTS["CAPACITY_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_packaging_component_payload(**overrides) -> dict:
    defaults = {
        "component_name": DEFAULTS["BOTTLE_NAME"],
        "component_type": "BOTTLE",
        "unit_cost_cents": 50,
        "initial_on_hand_units": DEFAULTS["COMPONENT_INITIAL_ON_HAND"],
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(formula_id, kettle_line_id, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "kettle_line_id": kettle_line_id,
        "planned_units": 2000,
        "scheduled_start": DEFAULTS["RUN_START"],
        "scheduled_end": DEFAULTS["RUN_END"],
        "packaging_requirements": [],
    }
    defaults.update(overrides)
    return defaults


def create_quality_hold_payload(production_run_id, **overrides) -> dict:
    defaults = {
        "production_run_id": production_run_id,
        "reason_category": "FOREIGN_MATERIAL",
    }
    defaults.update(overrides)
    return defaults


def create_label_approval_payload(formula_id, **overrides) -> dict:
    defaults = {
        "formula_id": formula_id,
        "label_version": "v1",
        "brand_display_name": "Acme",
        "net_quantity_statement": "12 fl oz",
        "allergen_declaration": "NONE",
    }
    defaults.update(overrides)
    return defaults
