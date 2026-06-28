"""Payload factories — one per entity, input fields only."""

DEFAULTS = {
    "EMAIL": "holder@example.com",
    "FULL_NAME": "Test Holder",
    "REGION": "NE01",
    "PLAN_TIER": "BASIC",
    "VISIT_INTERVAL_DAYS": 21,
    "PER_VISIT_PRICE_CENTS": 5000,
    "SEASONAL_PRICE_CENTS": 30000,
    "RETREAT_GUARANTEE_DAYS": 7,
    "LOT_SIZE_SQFT": 6000,
    "DAILY_CAPACITY": 4,
    "SEASON_START": "2026-05-01",
    "SEASON_END": "2026-08-31",
}


def create_service_plan_payload(**overrides) -> dict:
    defaults = {
        "tier": DEFAULTS["PLAN_TIER"],
        "visit_interval_days": DEFAULTS["VISIT_INTERVAL_DAYS"],
        "per_visit_price_cents": DEFAULTS["PER_VISIT_PRICE_CENTS"],
        "seasonal_price_cents": DEFAULTS["SEASONAL_PRICE_CENTS"],
        "includes_tick_barrier": False,
        "retreat_guarantee_days": DEFAULTS["RETREAT_GUARANTEE_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_account_holder_payload(**overrides) -> dict:
    defaults = {
        "email": DEFAULTS["EMAIL"],
        "full_name": DEFAULTS["FULL_NAME"],
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(account_holder_id, **overrides) -> dict:
    defaults = {
        "account_holder_id": account_holder_id,
        "street_address": "1 Test Way",
        "lot_size_sqft": DEFAULTS["LOT_SIZE_SQFT"],
        "service_region_code": DEFAULTS["REGION"],
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(**overrides) -> dict:
    defaults = {
        "label": "Yard",
        "zone_type": "TURF",
        "area_sqft": 4000,
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(property_id, service_plan_id, **overrides) -> dict:
    defaults = {
        "property_id": property_id,
        "service_plan_id": service_plan_id,
        "billing_mode": "PER_VISIT",
        "season_start_date": DEFAULTS["SEASON_START"],
        "season_end_date": DEFAULTS["SEASON_END"],
        "auto_renew": False,
    }
    defaults.update(overrides)
    return defaults


def create_crew_payload(**overrides) -> dict:
    defaults = {
        "tech_name": "Tech One",
        "home_region_code": DEFAULTS["REGION"],
        "daily_capacity": DEFAULTS["DAILY_CAPACITY"],
    }
    defaults.update(overrides)
    return defaults


def create_crew_route_payload(crew_id, **overrides) -> dict:
    defaults = {
        "crew_id": crew_id,
        "region_code": DEFAULTS["REGION"],
        "route_date": DEFAULTS["SEASON_START"],
    }
    defaults.update(overrides)
    return defaults


def create_weather_event_payload(**overrides) -> dict:
    defaults = {
        "region_code": DEFAULTS["REGION"],
        "event_date": DEFAULTS["SEASON_START"],
        "severity": "RAIN_HEAVY",
    }
    defaults.update(overrides)
    return defaults


def create_application_log_payload(treatment_zone_id, logged_by_tech_id, **overrides) -> dict:
    defaults = {
        "treatment_zone_id": treatment_zone_id,
        "product_code": "BIFEN_IT",
        "gallons_applied": 2.0,
        "logged_by_tech_id": logged_by_tech_id,
    }
    defaults.update(overrides)
    return defaults
