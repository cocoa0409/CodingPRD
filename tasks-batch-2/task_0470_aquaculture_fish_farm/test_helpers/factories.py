"""Payload factories — one per entity, input fields only.

Field names mirror the PRD exactly. Optional input fields (those the PRD marks
optional or defaulting) are omitted from defaults unless a test overrides them.
"""

DEFAULTS = {
    "SPECIES_COMMON_NAME": "Atlantic Salmon",
    "SPECIES_CODE": "SALM",
    "TARGET_MARKET_WEIGHT_G": 5000,
    "BASE_DAILY_GROWTH_G": 5.0,
    "DEFAULT_PROCESSING_YIELD_PCT": 0.62,
    "MIN_WATER_TEMP_C": 2,
    "MAX_WATER_TEMP_C": 18,
    "TANK_NAME": "T1",
    "TANK_KIND": "TANK",
    "VOLUME_LITERS": 100000,
    "MAX_BIOMASS_KG": 100000,
    "COHORT_LABEL": "C1",
    "FISH_COUNT": 1000,
    "STOCKED_AVG_WEIGHT_G": 50,
    "STOCKED_AT": "2026-01-01T00:00:00Z",
    "CUSTOMER_NAME": "Acme",
}


def create_species_payload(**overrides) -> dict:
    payload = {
        "common_name": DEFAULTS["SPECIES_COMMON_NAME"],
        "code": DEFAULTS["SPECIES_CODE"],
        "target_market_weight_g": DEFAULTS["TARGET_MARKET_WEIGHT_G"],
        "base_daily_growth_g": DEFAULTS["BASE_DAILY_GROWTH_G"],
        "default_processing_yield_pct": DEFAULTS["DEFAULT_PROCESSING_YIELD_PCT"],
        "min_water_temp_c": DEFAULTS["MIN_WATER_TEMP_C"],
        "max_water_temp_c": DEFAULTS["MAX_WATER_TEMP_C"],
    }
    payload.update(overrides)
    return payload


def create_tank_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["TANK_NAME"],
        "kind": DEFAULTS["TANK_KIND"],
        "volume_liters": DEFAULTS["VOLUME_LITERS"],
        "max_biomass_kg": DEFAULTS["MAX_BIOMASS_KG"],
    }
    payload.update(overrides)
    return payload


def create_broodstock_batch_payload(species_id, **overrides) -> dict:
    payload = {
        "species_id": species_id,
        "spawned_at": "2025-12-01T00:00:00Z",
        "fingerling_count": 1000,
    }
    payload.update(overrides)
    return payload


def create_cohort_payload(species_id, current_tank_id, **overrides) -> dict:
    payload = {
        "label": DEFAULTS["COHORT_LABEL"],
        "species_id": species_id,
        "current_tank_id": current_tank_id,
        "fish_count": DEFAULTS["FISH_COUNT"],
        "stocked_avg_weight_g": DEFAULTS["STOCKED_AVG_WEIGHT_G"],
        "stocked_at": DEFAULTS["STOCKED_AT"],
    }
    payload.update(overrides)
    return payload


def create_feed_log_payload(**overrides) -> dict:
    payload = {
        "fed_at": "2026-01-01T00:00:00Z",
        "amount_kg": 10,
        "feed_type": "starter",
    }
    payload.update(overrides)
    return payload


def create_water_quality_reading_payload(**overrides) -> dict:
    payload = {
        "measured_at": "2026-01-02T00:00:00Z",
        "dissolved_oxygen_mg_l": 8.0,
        "ammonia_mg_l": 0.1,
        "water_temp_c": 10.0,
    }
    payload.update(overrides)
    return payload


def create_stocking_event_payload(cohort_id, tank_id, **overrides) -> dict:
    payload = {
        "cohort_id": cohort_id,
        "tank_id": tank_id,
        "fish_count": 100,
        "stocked_at": "2026-01-01T00:00:00Z",
        "expected_harvest_at": "2026-06-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_grading_event_payload(source_cohort_id, planned_splits, **overrides) -> dict:
    payload = {
        "source_cohort_id": source_cohort_id,
        "planned_splits": planned_splits,
    }
    payload.update(overrides)
    return payload


def create_health_treatment_payload(cohort_id, tank_id, **overrides) -> dict:
    payload = {
        "cohort_id": cohort_id,
        "tank_id": tank_id,
        "medication": "oxytet",
        "started_at": "2026-01-01T00:00:00Z",
        "duration_days": 5,
        "withdrawal_days": 10,
    }
    payload.update(overrides)
    return payload


def create_harvest_order_payload(cohort_id, **overrides) -> dict:
    payload = {
        "cohort_id": cohort_id,
        "planned_fish_count": 500,
        "scheduled_at": "2026-01-05T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_processing_batch_payload(harvest_order_id, **overrides) -> dict:
    payload = {"harvest_order_id": harvest_order_id}
    payload.update(overrides)
    return payload


def create_sales_order_payload(**overrides) -> dict:
    payload = {"customer_name": DEFAULTS["CUSTOMER_NAME"]}
    payload.update(overrides)
    return payload


def create_sales_order_line_payload(product_lot_id, weight_kg, **overrides) -> dict:
    payload = {"product_lot_id": product_lot_id, "weight_kg": weight_kg}
    payload.update(overrides)
    return payload
