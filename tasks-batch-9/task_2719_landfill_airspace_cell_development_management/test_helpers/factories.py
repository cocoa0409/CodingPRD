"""Payload factories — one per resource, carrying only client-supplied inputs."""
from .constants import TEST_DEFAULTS


def landfill_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["LANDFILL_NAME"],
        "permit_number": TEST_DEFAULTS["PERMIT_NUMBER"],
        "permitted_total_airspace_cy": TEST_DEFAULTS["PERMITTED_TOTAL_AIRSPACE_CY"],
        "design_footprint_sf": TEST_DEFAULTS["DESIGN_FOOTPRINT_SF"],
        "planned_density_tons_per_cy": TEST_DEFAULTS["PLANNED_DENSITY_TONS_PER_CY"],
        "annual_tonnage_forecast": TEST_DEFAULTS["ANNUAL_TONNAGE_FORECAST"],
    }
    payload.update(overrides)
    return payload


def cell_payload(landfill_id: str, **overrides) -> dict:
    payload = {
        "landfill_id": landfill_id,
        "cell_code": TEST_DEFAULTS["CELL_CODE"],
        "design_airspace_cy": TEST_DEFAULTS["DESIGN_AIRSPACE_CY"],
        "design_area_sf": TEST_DEFAULTS["DESIGN_AREA_SF"],
        "liner_type": "DOUBLE_COMPOSITE",
        "construction_start_date": "2026-06-01T00:00:00Z",
        "construction_end_date": "2026-07-15T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def liner_qa_package_payload(cell_id: str, **overrides) -> dict:
    """Defaults score 100.00: 20/20 passing, 4000 ft of seam, 2 defects on 40 panels."""
    payload = {
        "cell_id": cell_id,
        "seam_length_ft": 4000,
        "destructive_test_count": 20,
        "passing_test_count": 20,
        "panel_count": 40,
        "defect_count": 2,
    }
    payload.update(overrides)
    return payload


def liner_qa_resubmit_payload(**overrides) -> dict:
    payload = {
        "seam_length_ft": 4000,
        "destructive_test_count": 20,
        "passing_test_count": 20,
        "panel_count": 40,
        "defect_count": 2,
    }
    payload.update(overrides)
    return payload


def aerial_survey_payload(landfill_id: str, **overrides) -> dict:
    payload = {
        "landfill_id": landfill_id,
        "flown_on": "2026-08-01T00:00:00Z",
        "coverage_period_start": "2026-06-01T00:00:00Z",
        "coverage_period_end": "2026-07-31T00:00:00Z",
        "measured_remaining_airspace_cy": 700000,
        "tons_placed_in_period": 250000,
    }
    payload.update(overrides)
    return payload


def operating_day_payload(landfill_id: str, active_cell_id: str, **overrides) -> dict:
    payload = {
        "landfill_id": landfill_id,
        "active_cell_id": active_cell_id,
        "operating_date": TEST_DEFAULTS["OPERATING_DATE"],
        "working_face_area_sf": TEST_DEFAULTS["WORKING_FACE_AREA_SF"],
        "cover_material_type": "ALTERNATIVE_TARP",
    }
    payload.update(overrides)
    return payload


def waste_load_payload(operating_day_id: str, **overrides) -> dict:
    payload = {
        "operating_day_id": operating_day_id,
        "hauler_ref": "H-1",
        "waste_stream": "MSW",
        "manifest_tons": 40.0,
        "load_check_result": "PASS",
    }
    payload.update(overrides)
    return payload


def special_waste_approval_payload(landfill_id: str, **overrides) -> dict:
    payload = {
        "landfill_id": landfill_id,
        "generator_name": "Northline Plating",
        "waste_code": "F006",
        "profile_stream": "INDUSTRIAL_SPECIAL",
        "approved_tons_cap": 500.0,
        "effective_from": "2026-07-01T00:00:00Z",
        "expires_on": "2026-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def treatment_agreement_payload(landfill_id: str, **overrides) -> dict:
    payload = {
        "landfill_id": landfill_id,
        "facility_name": TEST_DEFAULTS["FACILITY_NAME"],
        "daily_gallon_cap": TEST_DEFAULTS["DAILY_GALLON_CAP"],
        "base_haul_fee": TEST_DEFAULTS["BASE_HAUL_FEE"],
        "treatment_rate_per_kgal": TEST_DEFAULTS["TREATMENT_RATE_PER_KGAL"],
        "effective_from": "2026-01-01T00:00:00Z",
        "expires_on": "2027-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def leachate_shipment_payload(treatment_agreement_id: str, **overrides) -> dict:
    payload = {
        "treatment_agreement_id": treatment_agreement_id,
        "gallons": 4000,
        "window_start": "2026-08-01T08:00:00Z",
        "window_end": "2026-08-01T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def gas_well_payload(cell_id: str, **overrides) -> dict:
    payload = {"cell_id": cell_id, "well_code": "W-1", "depth_ft": 85}
    payload.update(overrides)
    return payload


def gas_well_tune_payload(**overrides) -> dict:
    """Defaults are within specification: methane 52.0, oxygen 2.0, vacuum 15.0."""
    payload = {
        "last_vacuum_in_h2o": 15.0,
        "last_methane_pct": 52.0,
        "last_oxygen_pct": 2.0,
    }
    payload.update(overrides)
    return payload


def surface_emission_scan_payload(landfill_id: str, **overrides) -> dict:
    payload = {
        "landfill_id": landfill_id,
        "scanned_on": "2026-08-01T00:00:00Z",
        "grid_points_count": 120,
        "max_reading_ppm": 120.0,
    }
    payload.update(overrides)
    return payload


def closure_cost_estimate_payload(landfill_id: str, expected_landfill_version, **overrides) -> dict:
    payload = {
        "landfill_id": landfill_id,
        "estimate_year": TEST_DEFAULTS["ESTIMATE_YEAR"],
        "closure_unit_cost_per_sf": TEST_DEFAULTS["CLOSURE_UNIT_COST_PER_SF"],
        "post_closure_annual_cost": TEST_DEFAULTS["POST_CLOSURE_ANNUAL_COST"],
        "inflation_pct": TEST_DEFAULTS["INFLATION_PCT"],
        "post_closure_years": 30,
        "expected_landfill_version": expected_landfill_version,
    }
    payload.update(overrides)
    return payload


def host_community_agreement_payload(landfill_id: str, **overrides) -> dict:
    payload = {
        "landfill_id": landfill_id,
        "community_name": TEST_DEFAULTS["COMMUNITY_NAME"],
        "posted_tipping_fee_per_ton": TEST_DEFAULTS["POSTED_TIPPING_FEE_PER_TON"],
        "host_fee_per_ton": TEST_DEFAULTS["HOST_FEE_PER_TON"],
        "tier1_monthly_tons": TEST_DEFAULTS["TIER1_MONTHLY_TONS"],
        "royalty_tier1_pct": TEST_DEFAULTS["ROYALTY_TIER1_PCT"],
        "royalty_tier2_pct": TEST_DEFAULTS["ROYALTY_TIER2_PCT"],
        "minimum_annual_payment": TEST_DEFAULTS["MINIMUM_ANNUAL_PAYMENT"],
        "effective_from": "2026-01-01T00:00:00Z",
        "expires_on": "2030-12-31T00:00:00Z",
    }
    payload.update(overrides)
    return payload
