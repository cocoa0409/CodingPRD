"""Payload factories — one per entity, input fields only.

Observation-time defaults sit at the logical clock startup default
(2026-08-01T00:00:00Z, PRD section 2.5) so they are never in the future.
"""
from .constants import TEST_DEFAULTS


def create_snow_event_payload(**overrides) -> dict:
    defaults = {
        "event_code": "SNOW-1",
        "season_label": TEST_DEFAULTS["SEASON_LABEL"],
        "chemical_limit_lbs": TEST_DEFAULTS["CHEMICAL_LIMIT_LBS"],
        "budget_cents": TEST_DEFAULTS["BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_surface_payload(**overrides) -> dict:
    defaults = {
        "surface_code": "RWY-09L",
        "surface_type": "RUNWAY",
        "length_ft": TEST_DEFAULTS["SURFACE_LENGTH_FT"],
        "width_ft": TEST_DEFAULTS["SURFACE_WIDTH_FT"],
        "priority_rank": 1,
    }
    defaults.update(overrides)
    return defaults


def create_condition_report_payload(event_id, surface_id,
                                    expected_surface_version,
                                    **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "surface_id": surface_id,
        "contaminant_type": "DRY_SNOW",
        "coverage_pct": 40,
        "depth_inches": 0.2,
        "observed_at": TEST_DEFAULTS["OBSERVED_AT"],
        "expected_surface_version": expected_surface_version,
    }
    defaults.update(overrides)
    return defaults


def create_friction_assessment_payload(event_id, surface_id,
                                       expected_surface_version,
                                       **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "surface_id": surface_id,
        "mu_value": 0.60,
        "measured_at": TEST_DEFAULTS["OBSERVED_AT"],
        "expected_surface_version": expected_surface_version,
    }
    defaults.update(overrides)
    return defaults


def create_notam_payload(event_id, surface_id, **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "surface_id": surface_id,
        "notam_type": "SURFACE_CONDITION",
        "effective_from": "2026-08-02T00:00:00Z",
        "effective_until": "2026-08-03T00:00:00Z",
        "message": "field condition notice",
    }
    defaults.update(overrides)
    return defaults


def create_chemical_product_payload(**overrides) -> dict:
    defaults = {
        "product_code": "NAAC-01",
        "base_rate_lbs_per_1000sqft": TEST_DEFAULTS["PRODUCT_BASE_RATE"],
        "unit_cost_cents_per_lb": TEST_DEFAULTS["PRODUCT_UNIT_COST"],
        "seasonal_limit_lbs": TEST_DEFAULTS["PRODUCT_SEASONAL_LIMIT"],
    }
    defaults.update(overrides)
    return defaults


def create_chemical_application_payload(event_id, surface_id, product_id,
                                        **overrides) -> dict:
    defaults = {
        "event_id": event_id,
        "surface_id": surface_id,
        "product_id": product_id,
        "pavement_temp_f": 20,
    }
    defaults.update(overrides)
    return defaults


def create_equipment_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_code": "PLOW-01",
        "unit_type": "PLOW",
        "hourly_rate_cents": TEST_DEFAULTS["UNIT_HOURLY_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_operator_shift_payload(event_id, **overrides) -> dict:
    defaults = {
        "operator_code": "OP-01",
        "event_id": event_id,
        "base_rate_cents_per_hour": TEST_DEFAULTS["SHIFT_BASE_RATE"],
        "start_utc": TEST_DEFAULTS["SHIFT_START"],
        "end_utc": TEST_DEFAULTS["SHIFT_END"],
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601="2026-08-10T00:00:00Z") -> dict:
    return {"to_iso8601": to_iso8601}
