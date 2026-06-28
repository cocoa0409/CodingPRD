"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "PLAN_NAME": "Gold",
    "TIER": "ENHANCED",
    "TERM_MONTHS": 60,
    "TERM_MILES": 100000,
    "MAX_VEHICLE_AGE_YEARS": 8,
    "MAX_ODOMETER_AT_SALE": 80000,
    "BASE_PREMIUM_CENTS": 200000,
    "DEDUCTIBLE_CENTS": 10000,
    "LABOR_RATE_CAP": 12000,
    "RENTAL_PER_DAY": 5000,
    "RENTAL_MAX_DAYS": 3,
    "TOWING_CENTS": 8000,
    "CESSION_PCT": 0.5,
    "SALE_PRICE_CENTS": 240000,
    "ODOMETER_AT_SALE": 20000,
    "VEHICLE_MODEL_YEAR": 2024,
    "SALE_DATE": "2026-01-01T00:00:00Z",
    "POSTED_LABOR_RATE": 9500,
}


def create_coverage_plan_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PLAN_NAME"],
        "tier": DEFAULTS["TIER"],
        "term_months": DEFAULTS["TERM_MONTHS"],
        "term_miles": DEFAULTS["TERM_MILES"],
        "max_vehicle_age_years": DEFAULTS["MAX_VEHICLE_AGE_YEARS"],
        "max_odometer_at_sale": DEFAULTS["MAX_ODOMETER_AT_SALE"],
        "base_premium_cents": DEFAULTS["BASE_PREMIUM_CENTS"],
        "deductible_cents": DEFAULTS["DEDUCTIBLE_CENTS"],
        "labor_rate_cap_cents_per_hour": DEFAULTS["LABOR_RATE_CAP"],
        "rental_benefit_cents_per_day": DEFAULTS["RENTAL_PER_DAY"],
        "rental_max_days": DEFAULTS["RENTAL_MAX_DAYS"],
        "towing_benefit_cents": DEFAULTS["TOWING_CENTS"],
        "reinsurance_cession_pct": DEFAULTS["CESSION_PCT"],
    }
    defaults.update(overrides)
    return defaults


def create_reinsurance_pool_payload(**overrides) -> dict:
    defaults = {"name": "Pool"}
    defaults.update(overrides)
    return defaults


def create_repair_facility_payload(**overrides) -> dict:
    defaults = {
        "name": "Shop",
        "posted_labor_rate_cents_per_hour": DEFAULTS["POSTED_LABOR_RATE"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(coverage_plan_id, reinsurance_pool_id, **overrides) -> dict:
    defaults = {
        "coverage_plan_id": coverage_plan_id,
        "reinsurance_pool_id": reinsurance_pool_id,
        "vin": "VIN00000001",
        "vehicle_model_year": DEFAULTS["VEHICLE_MODEL_YEAR"],
        "odometer_at_sale": DEFAULTS["ODOMETER_AT_SALE"],
        "sale_date": DEFAULTS["SALE_DATE"],
        "sale_price_cents": DEFAULTS["SALE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_ancillary_product_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "product_type": "GAP",
        "premium_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(contract_id, repair_facility_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "repair_facility_id": repair_facility_id,
        "odometer_at_claim": 40000,
        "claim_date": "2026-02-01T00:00:00Z",
        "complaint": "failure",
    }
    defaults.update(overrides)
    return defaults


def create_claim_line_payload(**overrides) -> dict:
    defaults = {"line_type": "PART"}
    defaults.update(overrides)
    return defaults


def create_cancellation_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "reason": "CUSTOMER_REQUEST",
        "request_date": "2026-01-20T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults
