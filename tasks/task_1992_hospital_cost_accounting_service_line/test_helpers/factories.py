"""Payload factories — one per entity, input fields only (PRD §3, §4)."""

DEFAULTS = {
    "SL_NAME": "Orthopedic Surgery",
    "SL_CODE": "ORTHO",
    "SL_BASE_DIRECT_COST": 9000.00,
    "SL_BUDGETED_VOLUME": 120,
    "PHYS_NPI": "1000000001",
    "PHYS_NAME": "Dr. One",
    "PHYS_SPECIALTY": "Orthopedics",
    "DRG_CODE": "470",
    "DRG_DESCRIPTION": "Major joint replacement",
    "DRG_TARGET_COST": 750.00,
    "DRG_BASE_RATE": 30000.00,
    "EXPECTED_REIMBURSEMENT": 30000.00,
    "CASE_PERIOD": "2026-08",
    "MODEL_EFFECTIVE_PERIOD": "2026-01",
}


def create_service_line_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["SL_NAME"],
        "code": DEFAULTS["SL_CODE"],
        "base_direct_cost": DEFAULTS["SL_BASE_DIRECT_COST"],
        "budgeted_volume": DEFAULTS["SL_BUDGETED_VOLUME"],
    }
    defaults.update(overrides)
    return defaults


def create_cost_center_payload(**overrides) -> dict:
    defaults = {
        "name": "OR Minutes",
        "code": "ORMINS",
        "cost_type": "INDIRECT",
        "cost_behavior": "VARIABLE",
        "allocated_cost": 12000.00,
        "capacity_measure": "MINUTES",
        "practical_capacity_minutes": 8000,
    }
    defaults.update(overrides)
    return defaults


def create_physician_payload(**overrides) -> dict:
    defaults = {
        "npi": DEFAULTS["PHYS_NPI"],
        "full_name": DEFAULTS["PHYS_NAME"],
        "specialty": DEFAULTS["PHYS_SPECIALTY"],
    }
    defaults.update(overrides)
    return defaults


def create_drg_payload(**overrides) -> dict:
    defaults = {
        "drg_code": DEFAULTS["DRG_CODE"],
        "description": DEFAULTS["DRG_DESCRIPTION"],
        "target_cost": DEFAULTS["DRG_TARGET_COST"],
        "base_rate": DEFAULTS["DRG_BASE_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_cost_model_payload(**overrides) -> dict:
    defaults = {
        "name": "ORTHO-STD",
        "allocation_basis": "TDABC",
        "rate_factor": 1.00,
        "effective_period": DEFAULTS["MODEL_EFFECTIVE_PERIOD"],
    }
    defaults.update(overrides)
    return defaults


def create_cost_model_refresh_payload(**overrides) -> dict:
    defaults = {
        "period": "2026-09",
        "proposed_rates": [],
        "data_quality_score": 95.0,
    }
    defaults.update(overrides)
    return defaults


def create_case_payload(**overrides) -> dict:
    defaults = {
        "period": DEFAULTS["CASE_PERIOD"],
        "expected_reimbursement": DEFAULTS["EXPECTED_REIMBURSEMENT"],
    }
    defaults.update(overrides)
    return defaults


def create_activity_line_payload(**overrides) -> dict:
    defaults = {
        "quantity": 100,
    }
    defaults.update(overrides)
    return defaults


def create_implant_payload(**overrides) -> dict:
    defaults = {
        "item_code": "HIP-1",
        "vendor": "V1",
        "unit_cost": 5000.00,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_supply_line_payload(**overrides) -> dict:
    defaults = {
        "supply_code": "S1",
        "unit_cost": 500.00,
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_payer_contract_payload(**overrides) -> dict:
    defaults = {
        "payer_name": "Medicare",
        "payer_type": "MEDICARE",
        "contracted_rate": 30000.00,
        "effective_period": DEFAULTS["MODEL_EFFECTIVE_PERIOD"],
    }
    defaults.update(overrides)
    return defaults


def create_budget_period_payload(**overrides) -> dict:
    defaults = {
        "period": DEFAULTS["CASE_PERIOD"],
        "static_budget_amount": 7000.00,
    }
    defaults.update(overrides)
    return defaults
