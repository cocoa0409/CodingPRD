"""Payload factories — one per write operation, input fields only."""

DEFAULTS = {
    "ZONE_CODE": "ZA-01",
    "AREA_SQFT": 9450,
    "HIVE_SLOT_CAPACITY": 8,
    "LABOR_BUDGET_USD": 20000.00,
    "VARIETY_NAME": "Merlice TOV",
    "CYCLE_LENGTH_WEEKS": 13,
    "FIRST_HARVEST_WEEK": 4,
    "PLANT_DENSITY_PER_SQFT": 0.24,
    "YIELD_CURVE": [0.4, 0.8, 1.1, 1.3, 1.3, 1.2, 1.0, 0.9, 0.7, 0.5],
    "GRADE_A_RATIO_PCT": 60,
    "EC_TARGET_MS": 3.0,
    "TRANSPLANT_DATE": "2026-08-03",
    "PLANTS_TRANSPLANTED": 2157,
    "HARVEST_WORKER_NAME": "Hana Ito",
    "SCOUT_WORKER_NAME": "Sera Vos",
    "HOURLY_RATE_USD": 19.50,
    "SCOUT_RATE_USD": 21.00,
}


def create_zone_payload(**overrides) -> dict:
    payload = {
        "code": DEFAULTS["ZONE_CODE"],
        "area_sqft": DEFAULTS["AREA_SQFT"],
        "glazing_type": "GLASS",
        "has_thermal_screen": True,
        "has_supplemental_lighting": True,
        "chp_connected": True,
        "hive_slot_capacity": DEFAULTS["HIVE_SLOT_CAPACITY"],
        "labor_budget_usd": DEFAULTS["LABOR_BUDGET_USD"],
    }
    payload.update(overrides)
    return payload


def create_variety_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["VARIETY_NAME"],
        "crop_type": "TOMATO",
        "cycle_length_weeks": DEFAULTS["CYCLE_LENGTH_WEEKS"],
        "first_harvest_week": DEFAULTS["FIRST_HARVEST_WEEK"],
        "plant_density_per_sqft": DEFAULTS["PLANT_DENSITY_PER_SQFT"],
        "yield_curve_lbs_per_sqft": list(DEFAULTS["YIELD_CURVE"]),
        "grade_a_ratio_pct": DEFAULTS["GRADE_A_RATIO_PCT"],
        "requires_pollination": True,
        "ec_target_ms": DEFAULTS["EC_TARGET_MS"],
    }
    payload.update(overrides)
    return payload


def create_crop_cycle_payload(zone_id: str, variety_id: str, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "variety_id": variety_id,
        "transplant_date": DEFAULTS["TRANSPLANT_DATE"],
        "plants_transplanted": DEFAULTS["PLANTS_TRANSPLANTED"],
    }
    payload.update(overrides)
    return payload


def create_worker_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["HARVEST_WORKER_NAME"],
        "skill": "HARVEST",
        "hourly_rate_usd": DEFAULTS["HOURLY_RATE_USD"],
        "productivity_index": 1.05,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_scout_worker_payload(**overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["SCOUT_WORKER_NAME"],
        "skill": "SCOUT",
        "hourly_rate_usd": DEFAULTS["SCOUT_RATE_USD"],
        "productivity_index": 1.00,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_climate_strategy_payload(
    zone_id: str, expected_zone_version: int, **overrides
) -> dict:
    payload = {
        "zone_id": zone_id,
        "regime": "DAY",
        "window_start": "2026-08-07T06:00:00Z",
        "window_end": "2026-08-07T18:00:00Z",
        "temp_setpoint_c": 21.5,
        "rh_setpoint_pct": 78,
        "co2_setpoint_ppm": 900,
        "lighting_hours": 6,
        "screen_position_pct": 40,
        "expected_zone_version": expected_zone_version,
    }
    payload.update(overrides)
    return payload


def record_climate_actuals_payload(**overrides) -> dict:
    payload = {
        "gas_consumed_m3": 900.00,
        "chp_generated_kwh": 1500.00,
        "grid_import_kwh": 400.00,
        "screen_deployed_hours": 6.00,
    }
    payload.update(overrides)
    return payload


def create_fertigation_batch_payload(zone_id: str, crop_cycle_id: str, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "crop_cycle_id": crop_cycle_id,
        "batch_date": "2026-08-06",
        "planned_volume_liters": 12000,
        "requested_recirculated_liters": 3000,
        "reservoir_ec_ms": 1.2,
        "target_ec_ms": 3.0,
        "target_ph": 5.8,
        "n_ppm": 180,
        "k_ppm": 320,
        "ca_ppm": 200,
        "drain_target_pct": 30,
    }
    payload.update(overrides)
    return payload


def create_drainage_reading_payload(**overrides) -> dict:
    payload = {
        "drain_volume_liters": 1200.00,
        "drain_ec_ms": 3.10,
        "reading_at": "2026-08-06T12:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_scouting_observation_payload(zone_id: str, crop_cycle_id: str, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "crop_cycle_id": crop_cycle_id,
        "observed_at": "2026-08-06T08:00:00Z",
        "pest_code": "WHITEFLY",
        "plants_inspected": 60,
        "pest_count_per_plant": 0.800,
    }
    payload.update(overrides)
    return payload


def create_bio_control_release_payload(zone_id: str, observation_id: str, **overrides) -> dict:
    payload = {
        "zone_id": zone_id,
        "observation_id": observation_id,
        "agent_code": "ENCARSIA",
        "planned_release_count": 6000,
        "planned_release_date": "2026-08-07",
    }
    payload.update(overrides)
    return payload


def create_labor_task_payload(
    zone_id: str, crop_cycle_id: str, worker_id: str, **overrides
) -> dict:
    payload = {
        "zone_id": zone_id,
        "crop_cycle_id": crop_cycle_id,
        "worker_id": worker_id,
        "task_type": "HARVEST",
        "window_start": "2026-08-07T07:00:00Z",
        "window_end": "2026-08-07T16:00:00Z",
        "planned_units": 4200,
        "standard_units_per_hour": 520,
    }
    payload.update(overrides)
    return payload


def create_harvest_lot_payload(crop_cycle_id: str, **overrides) -> dict:
    payload = {
        "crop_cycle_id": crop_cycle_id,
        "harvest_date": "2026-08-24",
        "gross_weight_lbs": 2000.00,
    }
    payload.update(overrides)
    return payload


def grade_harvest_lot_payload(**overrides) -> dict:
    payload = {"grade_a_lbs": 1200.00, "grade_b_lbs": 700.00, "cull_lbs": 100.00}
    payload.update(overrides)
    return payload


def create_retail_program_payload(**overrides) -> dict:
    payload = {
        "retailer_name": "Northline Grocers",
        "program_code": "NG-A1",
        "grade_spec": "A_ONLY",
        "weekly_commitment_lbs": 1000.00,
        "price_per_lb_usd": 1.85,
        "shortfall_penalty_per_lb_usd": 0.40,
        "priority_rank": 1,
        "status": "ACTIVE",
    }
    payload.update(overrides)
    return payload


def create_commitment_week_payload(program_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "iso_week": "2026-W36",
        "week_start_date": "2026-08-31",
    }
    payload.update(overrides)
    return payload


def create_posture_override_payload(**overrides) -> dict:
    payload = {
        "target_field": "ipm_posture",
        "target_value": "NORMAL",
        "override_reason": "Grower override for scheduled crew entry",
    }
    payload.update(overrides)
    return payload
