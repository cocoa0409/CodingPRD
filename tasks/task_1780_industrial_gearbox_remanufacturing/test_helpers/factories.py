"""Payload factories — one per entity, input fields only (PRD §4)."""

DEFAULTS = {
    "LEGAL_NAME": "Test Customer",
    "CREDIT_LIMIT_CENTS": 90_000_000,
    "SERIAL_NUMBER": "GBX-0001",
    "MODEL": "HZ-450",
    "RATED_TORQUE_NM": 12_000,
    "INTAKE_HOURS": 0,
    "QUOTED_ESTIMATE_CENTS": 100_000,
    "COMPONENT_CODE": "PINION_1",
    "CONDITION": "REGRINDABLE",
    "SEVERITY": 2,
    "NOTES": "wear",
    "ACTION": "REGRIND",
    "LABOR_HOURS": 2.0,
    "MATERIAL_CENTS": 5_000,
    "BACKLASH_MM": 0.10,
    "RADIAL_CLEARANCE_MM": 0.02,
    "AXIAL_CLEARANCE_MM": 0.02,
    "DURATION_MINUTES": 120,
    "MAX_TEMP_C": 80.0,
    "VIBRATION_MM_S": 2.0,
    "OIL_PARTICLE_COUNT": 1_500,
    "LOANER_SERIAL": "LN-0001",
    "START_DATE": "2026-08-10",
    "END_DATE": "2026-08-20",
    "DIRECTION": "OUTBOUND",
    "WEIGHT_KG": 400,
    "RIGGING_BAY_DATE": "2026-08-10",
    "RIGGING_BAY_HOURS": 2,
    "CLAIM_REASON": "noise",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "legal_name": DEFAULTS["LEGAL_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "serial_number": DEFAULTS["SERIAL_NUMBER"],
        "model": DEFAULTS["MODEL"],
        "rated_torque_nm": DEFAULTS["RATED_TORQUE_NM"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "intake_hours": DEFAULTS["INTAKE_HOURS"],
        "quoted_estimate_cents": DEFAULTS["QUOTED_ESTIMATE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_finding_payload(**overrides) -> dict:
    defaults = {
        "component_code": DEFAULTS["COMPONENT_CODE"],
        "condition": DEFAULTS["CONDITION"],
        "severity": DEFAULTS["SEVERITY"],
        "notes": DEFAULTS["NOTES"],
    }
    defaults.update(overrides)
    return defaults


def create_decision_payload(**overrides) -> dict:
    defaults = {
        "component_code": DEFAULTS["COMPONENT_CODE"],
        "action": DEFAULTS["ACTION"],
        "labor_hours": DEFAULTS["LABOR_HOURS"],
        "material_cents": DEFAULTS["MATERIAL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_assembly_record_payload(**overrides) -> dict:
    defaults = {
        "backlash_mm": DEFAULTS["BACKLASH_MM"],
        "radial_clearance_mm": DEFAULTS["RADIAL_CLEARANCE_MM"],
        "axial_clearance_mm": DEFAULTS["AXIAL_CLEARANCE_MM"],
    }
    defaults.update(overrides)
    return defaults


def create_run_in_test_payload(**overrides) -> dict:
    defaults = {
        "duration_minutes": DEFAULTS["DURATION_MINUTES"],
        "max_temp_c": DEFAULTS["MAX_TEMP_C"],
        "vibration_mm_s": DEFAULTS["VIBRATION_MM_S"],
        "oil_particle_count": DEFAULTS["OIL_PARTICLE_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_loaner_unit_payload(**overrides) -> dict:
    defaults = {
        "serial_number": DEFAULTS["LOANER_SERIAL"],
        "model": DEFAULTS["MODEL"],
    }
    defaults.update(overrides)
    return defaults


def create_loaner_assignment_payload(reman_order_id, **overrides) -> dict:
    defaults = {
        "reman_order_id": reman_order_id,
        "start_date": DEFAULTS["START_DATE"],
        "end_date": DEFAULTS["END_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "direction": DEFAULTS["DIRECTION"],
        "weight_kg": DEFAULTS["WEIGHT_KG"],
        "rigging_bay_date": DEFAULTS["RIGGING_BAY_DATE"],
        "rigging_bay_hours": DEFAULTS["RIGGING_BAY_HOURS"],
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "reported_hours": 100,
        "claim_reason": DEFAULTS["CLAIM_REASON"],
    }
    defaults.update(overrides)
    return defaults
