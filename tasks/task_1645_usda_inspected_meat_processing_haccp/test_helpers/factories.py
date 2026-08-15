"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    DAY_CLOCK_ISO,
    INSPECTOR_1,
    PRODUCTION_DATE,
    SHIFT_END_ISO,
    SHIFT_START_ISO,
)

DEFAULTS = {
    "ESTABLISHMENT_NUMBER": "EST-1645-BASE",
    "PLANT_NAME": "Prairie Packing",
    "DISTRICT_CODE": "D25",
    "COOLER_CAPACITY_LBS": 10000.0,
    "PROCESS_TYPE": "RAW_GROUND",
    "CCP_CODE": "CCP-1B",
    "HAZARD_CATEGORY": "BIOLOGICAL",
    "CCP_DESCRIPTION": "Carcass chill cooler",
    "MONITORING_FREQUENCY_MINUTES": 60,
    "SPECIES": "BOVINE",
    "SUPPLIER_NAME": "Verde Farms",
    "HEAD_COUNT": 10,
    "LIVE_WEIGHT_LBS": 12500.0,
    "HOT_CARCASS_WEIGHT_LBS": 1030.0,
    "COLD_CARCASS_WEIGHT_LBS": 1000.0,
    "PRIMAL_TYPE": "CHUCK",
    "CUT_WEIGHT_LBS": 600.0,
    "TRIM_WASTE_LBS": 400.0,
    "ORGANISM": "SALMONELLA",
    "SAMPLE_TYPE": "GROUND_PRODUCT",
    "PRODUCT_NAME": "Ground Beef 80/20",
    "FORMULATION_VERSION": 1,
    "UNITS_PRODUCED": 10,
    "UNIT_WEIGHT_LBS": 10.0,
    "SHELF_LIFE_DAYS": 10,
    "RECALL_SCOPE": "FULL",
}


def create_plant_payload(**overrides) -> dict:
    defaults = {
        "establishment_number": DEFAULTS["ESTABLISHMENT_NUMBER"],
        "name": DEFAULTS["PLANT_NAME"],
        "district_code": DEFAULTS["DISTRICT_CODE"],
        "cooler_capacity_lbs": DEFAULTS["COOLER_CAPACITY_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_haccp_plan_payload(**overrides) -> dict:
    defaults = {"process_type": DEFAULTS["PROCESS_TYPE"]}
    defaults.update(overrides)
    return defaults


def create_ccp_payload(**overrides) -> dict:
    defaults = {
        "ccp_code": DEFAULTS["CCP_CODE"],
        "hazard_category": DEFAULTS["HAZARD_CATEGORY"],
        "description": DEFAULTS["CCP_DESCRIPTION"],
        "critical_limit_max_f": 40.0,
        "monitoring_frequency_minutes": DEFAULTS["MONITORING_FREQUENCY_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def observation_payload(**overrides) -> dict:
    defaults = {"observed_value_f": 41.0}
    defaults.update(overrides)
    return defaults


def corrective_action_payload(**overrides) -> dict:
    defaults = {"corrective_action_note": "Rechilled product and re-monitored"}
    defaults.update(overrides)
    return defaults


def create_inspector_shift_payload(**overrides) -> dict:
    defaults = {
        "inspector_user_id": INSPECTOR_1,
        "scheduled_start": SHIFT_START_ISO,
        "scheduled_end": SHIFT_END_ISO,
    }
    defaults.update(overrides)
    return defaults


def create_production_day_payload(**overrides) -> dict:
    defaults = {
        "production_date": PRODUCTION_DATE,
        "process_type": DEFAULTS["PROCESS_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def receive_lot_payload(**overrides) -> dict:
    defaults = {
        "species": DEFAULTS["SPECIES"],
        "supplier_name": DEFAULTS["SUPPLIER_NAME"],
        "head_count": DEFAULTS["HEAD_COUNT"],
        "live_weight_lbs": DEFAULTS["LIVE_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def harvest_payload(**overrides) -> dict:
    defaults = {"hot_carcass_weight_lbs": DEFAULTS["HOT_CARCASS_WEIGHT_LBS"]}
    defaults.update(overrides)
    return defaults


def chill_complete_payload(**overrides) -> dict:
    defaults = {"cold_carcass_weight_lbs": DEFAULTS["COLD_CARCASS_WEIGHT_LBS"]}
    defaults.update(overrides)
    return defaults


def complete_fabrication_payload(**overrides) -> dict:
    defaults = {"trim_waste_lbs": DEFAULTS["TRIM_WASTE_LBS"]}
    defaults.update(overrides)
    return defaults


def release_hold_payload(**overrides) -> dict:
    defaults = {"disposition_note": "Confirmation retest negative; released"}
    defaults.update(overrides)
    return defaults


def cut_record_payload(**overrides) -> dict:
    defaults = {
        "primal_type": DEFAULTS["PRIMAL_TYPE"],
        "weight_lbs": DEFAULTS["CUT_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def pathogen_sample_payload(**overrides) -> dict:
    defaults = {
        "organism": DEFAULTS["ORGANISM"],
        "sample_type": DEFAULTS["SAMPLE_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def report_result_payload(**overrides) -> dict:
    defaults = {"result": "NEGATIVE"}
    defaults.update(overrides)
    return defaults


def create_label_approval_payload(**overrides) -> dict:
    defaults = {
        "product_name": DEFAULTS["PRODUCT_NAME"],
        "claims": ["NATURAL"],
        "substantiation_doc_refs": ["doc-nat-1"],
        "formulation_version": DEFAULTS["FORMULATION_VERSION"],
    }
    defaults.update(overrides)
    return defaults


def create_finished_lot_payload(**overrides) -> dict:
    defaults = {
        "source_lot_id": None,
        "label_approval_id": None,
        "units_produced": DEFAULTS["UNITS_PRODUCED"],
        "unit_weight_lbs": DEFAULTS["UNIT_WEIGHT_LBS"],
        "shelf_life_days": DEFAULTS["SHELF_LIFE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def log_temperature_payload(**overrides) -> dict:
    defaults = {"temp_f": 38.0}
    defaults.update(overrides)
    return defaults


def humane_audit_payload(**overrides) -> dict:
    defaults = {
        "production_day_id": None,
        "stunning_efficacy_pct": 99.5,
        "slips_falls_pct": 2.0,
        "vocalization_pct": 5.0,
    }
    defaults.update(overrides)
    return defaults


def appeal_payload(**overrides) -> dict:
    defaults = {"appeal_note": "We dispute the finding"}
    defaults.update(overrides)
    return defaults


def resolve_payload(**overrides) -> dict:
    defaults = {"resolution_note": "Corrective action verified on site"}
    defaults.update(overrides)
    return defaults


def create_recall_exercise_payload(**overrides) -> dict:
    defaults = {
        "target_finished_lot_id": None,
        "scope": DEFAULTS["RECALL_SCOPE"],
    }
    defaults.update(overrides)
    return defaults


def complete_recall_payload(**overrides) -> dict:
    defaults = {"reconciled_weight_lbs": 1000.0}
    defaults.update(overrides)
    return defaults


def set_clock_payload(**overrides) -> dict:
    defaults = {"to_iso8601": DAY_CLOCK_ISO}
    defaults.update(overrides)
    return defaults
