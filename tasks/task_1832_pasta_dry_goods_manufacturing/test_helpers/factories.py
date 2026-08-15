"""Payload factories — one per entity, input fields only."""
from .constants import CERT_DEFAULTS, LAB_DEFAULTS, RUN_END_ISO, RUN_START_ISO


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "contract_code": "C-1",
        "supplier_name": "Durum Co",
        "ingredient_type": "SEMOLINA",
        "base_price_cents_per_kg": 500,
        "reference_index_value": 100.0,
        "pricing_method": "INDEX_LAGGED",
        "effective_start": "2026-01-01",
        "effective_end": "2026-12-31",
    }
    defaults.update(overrides)
    return defaults


def index_reading_payload(effective_date="2026-08-01", index_value=110.0, **overrides) -> dict:
    payload = {"effective_date": effective_date, "index_value": index_value}
    payload.update(overrides)
    return payload


def create_lot_payload(contract_id, received_weight_kg=100.0,
                       delivery_date="2026-08-01", **overrides) -> dict:
    payload = {
        "contract_id": contract_id,
        "delivery_date": delivery_date,
        "received_weight_kg": received_weight_kg,
    }
    payload.update(CERT_DEFAULTS)
    payload.update(overrides)
    return payload


def lot_lab_results_payload(**overrides) -> dict:
    payload = dict(LAB_DEFAULTS)
    payload.update(overrides)
    return payload


def create_recipe_payload(**overrides) -> dict:
    defaults = {
        "recipe_name": "Penne",
        "brand_type": "BRANDED",
        "shape_family": "LONG_CUT",
        "gluten_free": False,
        "target_moisture_pct": 12.5,
        "drying_curve": "STANDARD",
        "shelf_life_days": 365,
        "unit_weight_g": 500,
        "units_per_case": 30,
        "case_weight_limit_kg": 12.0,
        "cases_per_pallet": 40,
        "ingredients": [
            {"ingredient_type": "SEMOLINA", "percentage": 100.0, "min_protein_pct": 12.0}
        ],
    }
    defaults.update(overrides)
    return defaults


def create_line_payload(line_name="L-1", **overrides) -> dict:
    payload = {"line_name": line_name}
    payload.update(overrides)
    return payload


def create_die_payload(die_code="D-1", shape_family="LONG_CUT",
                       rated_capacity_kg=100000.0, **overrides) -> dict:
    payload = {
        "die_code": die_code,
        "shape_family": shape_family,
        "rated_capacity_kg": rated_capacity_kg,
    }
    payload.update(overrides)
    return payload


def create_run_payload(recipe_id, line_id, semolina_lot_id, expected_line_version,
                       planned_input_kg=500.0, scheduled_start=RUN_START_ISO,
                       scheduled_end=RUN_END_ISO, **overrides) -> dict:
    payload = {
        "recipe_id": recipe_id,
        "line_id": line_id,
        "semolina_lot_id": semolina_lot_id,
        "planned_input_kg": planned_input_kg,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_line_version": expected_line_version,
    }
    payload.update(overrides)
    return payload


def reschedule_run_payload(expected_run_version, **overrides) -> dict:
    payload = {"expected_run_version": expected_run_version}
    payload.update(overrides)
    return payload


def create_zone_payload(zone_name="Z-1", zone_type="CONVENTIONAL",
                        capacity_pallets=10, **overrides) -> dict:
    payload = {
        "zone_name": zone_name,
        "zone_type": zone_type,
        "capacity_pallets": capacity_pallets,
    }
    payload.update(overrides)
    return payload


def create_pest_inspection_payload(zone_id, severity="NONE", **overrides) -> dict:
    payload = {"zone_id": zone_id, "severity": severity}
    payload.update(overrides)
    return payload


def create_gluten_test_payload(test_type="LINE_SWAB", result="PASS", **overrides) -> dict:
    payload = {"test_type": test_type, "result": result}
    payload.update(overrides)
    return payload
