"""Payload factories — one per entity, input fields only (PRD §3, §4)."""


def create_parcel_payload(**overrides) -> dict:
    """POST /parcels input (PRD §3.1): name, acreage, soil_type."""
    defaults = {"name": "Test Parcel", "acreage": 100.0, "soil_type": "LOAM"}
    defaults.update(overrides)
    return defaults


def create_crop_plan_payload(parcel_id, **overrides) -> dict:
    """POST /crop-plans input (PRD §3.1)."""
    defaults = {
        "parcel_id": parcel_id,
        "crop": "CORN",
        "season_year": 2026,
        "planned_acres": 50.0,
        "budget_input_cost": 100.0,
        "budget_labor_cost": 100.0,
        "budget_equipment_cost": 100.0,
    }
    defaults.update(overrides)
    return defaults


def approve_crop_plan_payload(expected_parcel_version, **overrides) -> dict:
    """POST /crop-plans/{id}/approve input (PRD §2.6, §3.1)."""
    defaults = {"expected_parcel_version": expected_parcel_version}
    defaults.update(overrides)
    return defaults


def create_input_product_payload(**overrides) -> dict:
    """POST /input-products input (PRD §3.3). restricted_use defaults false;
    REI/PHI required when restricted_use true, else default to zero."""
    defaults = {
        "name": "Test Product",
        "category": "SEED",
        "unit": "SEED_UNIT",
        "unit_cost": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_input_lot_payload(input_product_id, **overrides) -> dict:
    """POST /input-lots input (PRD §3.3)."""
    defaults = {
        "input_product_id": input_product_id,
        "lot_code": "LOT-1",
        "quantity_received": 500.0,
    }
    defaults.update(overrides)
    return defaults


def create_application_record_payload(crop_plan_id, input_product_id, applicator_user_id, **overrides) -> dict:
    """POST /application-records input (PRD §3.4)."""
    defaults = {
        "crop_plan_id": crop_plan_id,
        "input_product_id": input_product_id,
        "applicator_user_id": applicator_user_id,
        "rate_per_acre": 2.0,
        "acres_treated": 40.0,
    }
    defaults.update(overrides)
    return defaults


def create_planting_event_payload(crop_plan_id, input_lot_id, **overrides) -> dict:
    """POST /planting-events input (PRD §3.5)."""
    defaults = {
        "crop_plan_id": crop_plan_id,
        "input_lot_id": input_lot_id,
        "acres_planted": 40.0,
        "seed_rate_per_acre": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_harvest_event_payload(crop_plan_id, **overrides) -> dict:
    """POST /harvest-events input (PRD §3.5)."""
    defaults = {
        "crop_plan_id": crop_plan_id,
        "acres_harvested": 40.0,
        "gross_quantity": 1000.0,
        "moisture_pct": 0.0,
    }
    defaults.update(overrides)
    return defaults


def create_harvest_lot_payload(harvest_event_id, **overrides) -> dict:
    """POST /harvest-lots input (PRD §3.6)."""
    defaults = {"harvest_event_id": harvest_event_id, "quantity": 1000.0}
    defaults.update(overrides)
    return defaults


def grade_harvest_lot_payload(grade, **overrides) -> dict:
    """POST /harvest-lots/{id}/grade input (PRD §3.6)."""
    defaults = {"grade": grade}
    defaults.update(overrides)
    return defaults


def create_sale_contract_payload(**overrides) -> dict:
    """POST /sale-contracts input (PRD §3.9). min_quality optional (default GRADE_B)."""
    defaults = {
        "crop": "CORN",
        "buyer_name": "Test Buyer",
        "contracted_quantity": 1000.0,
        "price_per_unit": 5.0,
    }
    defaults.update(overrides)
    return defaults


def commit_lot_payload(harvest_lot_id, commit_quantity, **overrides) -> dict:
    """POST /sale-contracts/{id}/commit-lot input (PRD §3.9)."""
    defaults = {"harvest_lot_id": harvest_lot_id, "commit_quantity": commit_quantity}
    defaults.update(overrides)
    return defaults


def create_equipment_asset_payload(**overrides) -> dict:
    """POST /equipment-assets input (PRD §3.8)."""
    defaults = {"name": "Test Asset", "kind": "TRACTOR", "hourly_cost": 50.0}
    defaults.update(overrides)
    return defaults


def create_equipment_usage_payload(equipment_asset_id, crop_plan_id, window_start, window_end, **overrides) -> dict:
    """POST /equipment-usages input (PRD §3.8)."""
    defaults = {
        "equipment_asset_id": equipment_asset_id,
        "crop_plan_id": crop_plan_id,
        "window_start": window_start,
        "window_end": window_end,
    }
    defaults.update(overrides)
    return defaults


def create_labor_entry_payload(crop_plan_id, **overrides) -> dict:
    """POST /labor-entries input (PRD §3.8)."""
    defaults = {
        "crop_plan_id": crop_plan_id,
        "worker_name": "Worker 1",
        "hours": 10.0,
        "hourly_rate": 20.0,
    }
    defaults.update(overrides)
    return defaults


def create_irrigation_event_payload(parcel_id, window_start, window_end, **overrides) -> dict:
    """POST /irrigation-events input (PRD §3.8)."""
    defaults = {
        "parcel_id": parcel_id,
        "window_start": window_start,
        "window_end": window_end,
        "inches_applied": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_applicator_payload(**overrides) -> dict:
    """POST /applicators input (PRD §3.10). certified defaults true."""
    defaults = {"full_name": "Test Applicator", "license_no": "RU-100"}
    defaults.update(overrides)
    return defaults
