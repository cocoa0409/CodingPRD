"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "CARRIER_NAME": "Acme",
    "POLICY_NUMBER": "P-TEST",
    "PERIL": "WATER",
    "COVERAGE_LIMIT_CENTS": 500_000,
    "PROPERTY_ADDRESS": "1 Main",
    "LOSS_TYPE": "WATER",
    "WATER_CATEGORY": 1,
    "WATER_CLASS": 1,
    "TECH_NAME": "Tech A",
    "CERTIFICATION": "ASD",
    "ASSET_TAG": "AM-1",
    "EQUIPMENT_KIND": "AIR_MOVER",
    "ROOM_LABEL": "R1",
    "FLOOR_AREA_SQFT": 100,
    "WET_WALL_LINEAR_FT": 0,
    "DEHU_PPD_RATING": 70,
    "DRY_STANDARD_PCT": 12,
    "ESTIMATED_DRYING_DAYS": 2,
    "DECLARED_VALUE_CENTS": 50_000,
    "CONTENTS_DESCRIPTION": "Sofa",
}


def create_claim_payload(**overrides) -> dict:
    """InsuranceClaim input fields. carrier_name, policy_number, peril,
    coverage_limit_cents required; deductible_cents/depreciation_pct/tax_pct
    optional (default 0)."""
    defaults = {
        "carrier_name": DEFAULTS["CARRIER_NAME"],
        "policy_number": DEFAULTS["POLICY_NUMBER"],
        "peril": DEFAULTS["PERIL"],
        "coverage_limit_cents": DEFAULTS["COVERAGE_LIMIT_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_job_payload(claim_id, **overrides) -> dict:
    """LossJob FNOL intake. claim_id, property_address, loss_type required;
    water_category/water_class required only for WATER loss."""
    defaults = {
        "claim_id": claim_id,
        "property_address": DEFAULTS["PROPERTY_ADDRESS"],
        "loss_type": DEFAULTS["LOSS_TYPE"],
        "water_category": DEFAULTS["WATER_CATEGORY"],
        "water_class": DEFAULTS["WATER_CLASS"],
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    """Technician pool entry. full_name, certification required; active optional
    (default true)."""
    defaults = {
        "full_name": DEFAULTS["TECH_NAME"],
        "certification": DEFAULTS["CERTIFICATION"],
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(**overrides) -> dict:
    """EquipmentUnit pool entry. asset_tag, kind required."""
    defaults = {
        "asset_tag": DEFAULTS["ASSET_TAG"],
        "kind": DEFAULTS["EQUIPMENT_KIND"],
    }
    defaults.update(overrides)
    return defaults


def create_chamber_payload(job_id, **overrides) -> dict:
    """DryingChamber. job_id, room_label, floor_area_sqft, dehu_ppd_rating,
    dry_standard_pct required; wet_wall_linear_ft optional (default 0)."""
    defaults = {
        "job_id": job_id,
        "room_label": DEFAULTS["ROOM_LABEL"],
        "floor_area_sqft": DEFAULTS["FLOOR_AREA_SQFT"],
        "wet_wall_linear_ft": DEFAULTS["WET_WALL_LINEAR_FT"],
        "dehu_ppd_rating": DEFAULTS["DEHU_PPD_RATING"],
        "dry_standard_pct": DEFAULTS["DRY_STANDARD_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_placement_payload(job_id, chamber_id, equipment_unit_id, **overrides) -> dict:
    """EquipmentPlacement. job_id, chamber_id, equipment_unit_id required."""
    defaults = {
        "job_id": job_id,
        "chamber_id": chamber_id,
        "equipment_unit_id": equipment_unit_id,
    }
    defaults.update(overrides)
    return defaults


def create_reading_payload(**overrides) -> dict:
    """MoistureReading. temp_f, relative_humidity_pct, moisture_content_pct
    required (gpp/monitoring_day/job_id/chamber_id are computed/system)."""
    defaults = {
        "temp_f": 78,
        "relative_humidity_pct": 55,
        "moisture_content_pct": 20,
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(job_id, expected_job_version, **overrides) -> dict:
    """ScopeEstimate. job_id, estimated_drying_days, line_items,
    expected_job_version required."""
    defaults = {
        "job_id": job_id,
        "estimated_drying_days": DEFAULTS["ESTIMATED_DRYING_DAYS"],
        "line_items": [{"qty": 1, "unit_price_cents": 5000}],
        "expected_job_version": expected_job_version,
    }
    defaults.update(overrides)
    return defaults


def create_contents_payload(job_id, **overrides) -> dict:
    """ContentsItem pack-out. job_id, description, declared_value_cents required."""
    defaults = {
        "job_id": job_id,
        "description": DEFAULTS["CONTENTS_DESCRIPTION"],
        "declared_value_cents": DEFAULTS["DECLARED_VALUE_CENTS"],
    }
    defaults.update(overrides)
    return defaults
