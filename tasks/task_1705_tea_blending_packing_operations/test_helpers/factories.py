"""Payload factories — one per creatable resource, input fields only."""

DEFAULTS = {
    "SUPPLIER_NAME": "Assam Co",
    "ORIGIN_REGION": "Assam",
    "LEAF_TYPE": "BLACK",
    "HARVEST_DATE": "2026-02-01",
    "WEIGHT_KG": 10.0,
    "COST_PER_KG_CENTS": 900,
    "MOISTURE_PCT": 5.0,
    "AROMA": 80,
    "BRISKNESS": 80,
    "APPEARANCE": 80,
    "LAB_NAME": "LabA",
    "TEST_METHOD": "GCMS",
    "PASS_PPM": 0.20,
    "FLAVORING_NAME": "Bergamot",
    "FLAVORING_COST_PER_KG_CENTS": 2000,
    "RECIPE_NAME": "House Blend",
    "TARGET_WEIGHT_KG": 20.0,
    "LINE_NAME": "LP-1",
    "LINE_TYPE": "LOOSE_PACK",
    "PLANNED_UNITS": 100,
    "CUSTOMER_NAME": "Acme Foods",
    "MINIMUM_UNITS_PER_RUN": 100,
    "CONTRACTED_TOTAL_UNITS": 1000,
    "BASE_UNIT_PRICE_CENTS": 200,
    "CERT_VOLUME_KG": 10000.0,
    "VALID_FROM": "2026-01-01",
    "VALID_UNTIL": "2026-12-31",
}


def create_supplier_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SUPPLIER_NAME"],
        "origin_region": DEFAULTS["ORIGIN_REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_leaf_lot_payload(supplier_id, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "leaf_type": DEFAULTS["LEAF_TYPE"],
        "harvest_date": DEFAULTS["HARVEST_DATE"],
        "weight_kg": DEFAULTS["WEIGHT_KG"],
        "cost_per_kg_cents": DEFAULTS["COST_PER_KG_CENTS"],
        "moisture_pct": DEFAULTS["MOISTURE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_grade_assessment_payload(**overrides) -> dict:
    defaults = {
        "aroma_score": DEFAULTS["AROMA"],
        "briskness_score": DEFAULTS["BRISKNESS"],
        "appearance_score": DEFAULTS["APPEARANCE"],
    }
    defaults.update(overrides)
    return defaults


def create_residue_test_payload(**overrides) -> dict:
    defaults = {
        "lab_name": DEFAULTS["LAB_NAME"],
        "measured_residue_ppm": DEFAULTS["PASS_PPM"],
        "test_method": DEFAULTS["TEST_METHOD"],
    }
    defaults.update(overrides)
    return defaults


def create_flavoring_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["FLAVORING_NAME"],
        "allergen_tags": [],
        "natural_certified": True,
        "cost_per_kg_cents": DEFAULTS["FLAVORING_COST_PER_KG_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def single_component(leaf_type="GREEN", min_grade="C", pct=100.0):
    return {"leaf_type": leaf_type, "min_grade": min_grade, "pct": pct}


def create_recipe_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["RECIPE_NAME"],
        "certification_target": "CONVENTIONAL",
        "pack_format": "LOOSE_PACK",
        "components": [single_component()],
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(recipe_id, **overrides) -> dict:
    defaults = {
        "recipe_id": recipe_id,
        "target_weight_kg": DEFAULTS["TARGET_WEIGHT_KG"],
    }
    defaults.update(overrides)
    return defaults


def create_allocation_payload(lot_id, allocated_kg, expected_batch_version,
                              **overrides) -> dict:
    defaults = {
        "lot_id": lot_id,
        "allocated_kg": allocated_kg,
        "expected_batch_version": expected_batch_version,
    }
    defaults.update(overrides)
    return defaults


def create_blend_payload(measured_moisture_pct=5.0, **overrides) -> dict:
    defaults = {"measured_moisture_pct": measured_moisture_pct}
    defaults.update(overrides)
    return defaults


def create_flavoring_application_payload(flavoring_id, applied_kg,
                                         **overrides) -> dict:
    defaults = {"flavoring_id": flavoring_id, "applied_kg": applied_kg}
    defaults.update(overrides)
    return defaults


def create_packaging_line_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["LINE_NAME"],
        "line_type": DEFAULTS["LINE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def create_run_payload(line_id, batch_id, planned_start, planned_end,
                       planned_units, **overrides) -> dict:
    defaults = {
        "line_id": line_id,
        "batch_id": batch_id,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "planned_units": planned_units,
    }
    defaults.update(overrides)
    return defaults


def create_complete_run_payload(actual_units, **overrides) -> dict:
    defaults = {"actual_units": actual_units}
    defaults.update(overrides)
    return defaults


def create_contract_payload(recipe_id, **overrides) -> dict:
    defaults = {
        "customer_name": DEFAULTS["CUSTOMER_NAME"],
        "recipe_id": recipe_id,
        "minimum_units_per_run": DEFAULTS["MINIMUM_UNITS_PER_RUN"],
        "contracted_total_units": DEFAULTS["CONTRACTED_TOTAL_UNITS"],
        "base_unit_price_cents": DEFAULTS["BASE_UNIT_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_certificate_payload(supplier_id, **overrides) -> dict:
    defaults = {
        "supplier_id": supplier_id,
        "cert_type": "ORGANIC",
        "total_volume_kg": DEFAULTS["CERT_VOLUME_KG"],
        "valid_from": DEFAULTS["VALID_FROM"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}
