"""Payload factories — one per entity, input fields only."""
import itertools

_counter = itertools.count(1)


def _seq() -> int:
    return next(_counter)


DEFAULTS = {
    "COMPANY_NAME": "Test Co",
    "VOLUME_LITERS": 800,
    "TARGET_CONC": 5.0,
    "LOW_CONC": 4.0,
    "HIGH_CONC": 6.0,
    "AMP_HOUR_CAPACITY": 600,
}


def create_customer_payload(**overrides) -> dict:
    defaults = {"company_name": f"{DEFAULTS['COMPANY_NAME']} {_seq()}"}
    defaults.update(overrides)
    return defaults


def create_fixture_payload(**overrides) -> dict:
    defaults = {
        "fixture_code": f"RACK-{_seq():04d}",
        "routing_mode": "RACK",
        "capacity_dm2": 500,
        "purchase_cost_cents": 120000,
        "rated_uses": 50,
    }
    defaults.update(overrides)
    return defaults


def create_alloy_rule_payload(**overrides) -> dict:
    defaults = {
        "alloy_code": f"AL{_seq():04d}",
        "process_type": "ANODIZE",
        "chemistry_family": "SULFURIC",
        "compatibility": "COMPATIBLE",
    }
    defaults.update(overrides)
    return defaults


def create_bath_payload(**overrides) -> dict:
    defaults = {
        "bath_code": f"ANO-{_seq():04d}",
        "process_type": "ANODIZE",
        "chemistry_family": "SULFURIC",
        "routing_modes_supported": ["RACK", "BARREL"],
        "volume_liters": DEFAULTS["VOLUME_LITERS"],
        "target_concentration_g_l": DEFAULTS["TARGET_CONC"],
        "low_concentration_g_l": DEFAULTS["LOW_CONC"],
        "high_concentration_g_l": DEFAULTS["HIGH_CONC"],
        "amp_hour_capacity": DEFAULTS["AMP_HOUR_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_titration_payload(**overrides) -> dict:
    # 50.0 ml x 0.1 N x 49.0 / 49.0 ml == 5.000 g/L for a SULFURIC bath
    defaults = {
        "titrant_volume_ml": 50.0,
        "titrant_normality": 0.1,
        "sample_volume_ml": 49.0,
    }
    defaults.update(overrides)
    return defaults


def create_dose_payload(**overrides) -> dict:
    defaults = {
        "chemical_code": "H2SO4",
        "quantity_g": 10.0,
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "part_number": f"PN-{_seq():04d}",
        "alloy_code": "AL6061",
        "process_type": "ANODIZE",
        "routing_mode": "BARREL",
        "part_count": 10,
        "surface_area_dm2_per_part": 2.5,
        "thickness_spec_min_um": 12.0,
        "thickness_spec_max_um": 18.0,
    }
    defaults.update(overrides)
    return defaults


def create_load_run_payload(**overrides) -> dict:
    defaults = {
        "duration_minutes": 40,
        "current_density_a_dm2": 1.5,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_payload(**overrides) -> dict:
    defaults = {
        "thickness_readings_um": [13.0, 14.0, 15.0],
        "defect_type": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_salt_spray_lot_payload(**overrides) -> dict:
    defaults = {
        "sample_count": 5,
        "hours_required": 96,
    }
    defaults.update(overrides)
    return defaults


def create_discharge_permit_payload(**overrides) -> dict:
    defaults = {
        "outfall_code": f"OUTFALL-{_seq():03d}",
        "effective_from": "2026-08-01",
        "effective_to": "2026-08-31",
        "limits": [
            {"analyte_code": "NICKEL", "max_concentration_mg_l": 2.0, "monthly_mass_cap_g": 500.0}
        ],
    }
    defaults.update(overrides)
    return defaults


def create_waste_sample_payload(**overrides) -> dict:
    defaults = {
        "flow_liters": 1000,
        "readings": [{"analyte_code": "NICKEL", "concentration_mg_l": 1.0}],
    }
    defaults.update(overrides)
    return defaults


def create_waste_manifest_payload(**overrides) -> dict:
    defaults = {"generator_epa_id": f"EPA-GEN-{_seq():04d}"}
    defaults.update(overrides)
    return defaults


def create_manifest_line_item_payload(**overrides) -> dict:
    defaults = {
        "waste_code": "F006",
        "source_type": "SLUDGE_PRESS",
        "description": "Filter press cake",
        "volume_liters": 100,
    }
    defaults.update(overrides)
    return defaults
