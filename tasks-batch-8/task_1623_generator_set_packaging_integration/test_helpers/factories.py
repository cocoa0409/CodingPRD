"""Payload factories — one per entity, input fields only (PRD §3)."""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Customer",
    "CREDIT_LIMIT_CENTS": 200000000,
    "LOCALE": "US_TX",
    "ENGINE_MODEL_CODE": "E15",
    "ENGINE_MANUFACTURER": "Generac",
    "ENGINE_RATED_KW": 400,
    "ENGINE_BURN_GPH": 15.0,
    "ENGINE_TIER": "EPA_TIER_4",
    "ENGINE_LIST_PRICE_CENTS": 30000000,
    "ALT_MODEL_CODE": "A700",
    "ALT_RATED_KVA": 700,
    "ALT_EFFICIENCY_PCT": 96.0,
    "ALT_LIST_PRICE_CENTS": 15000000,
    "OCCUPANCY_TYPE": "STANDARD",
    "APPLICATION": "STANDBY",
    "LARGEST_MOTOR_KVA": 100,
    "STARTING_METHOD": "DOL",
    "ALTITUDE_M": 500,
    "AMBIENT_C": 40,
    "SIZING_METHOD": "NAMEPLATE_SUM",
    "ENCLOSURE_TYPE": "OPEN",
    "ENCLOSURE_PRICE_CENTS": 2000000,
    "FUEL_TANK_GALLONS": 400,
    "BAY_CODE": "B1",
    "BAY_MAX_KW": 1000,
    "SLOT_SERVICE_DATE": "2026-09-10",
    "WINDOW_START_HOUR": 8,
    "WINDOW_END_HOUR": 16,
    "LIFT_HOURS": 2.0,
    "GROSS_WEIGHT_KG": 12000,
    "FREIGHT_CLASS": "STANDARD",
    "TEST_SERVICE_DATE": "2026-08-05",
    "SYNC_MODE": "ISOLATED",
    "MAX_UNITS": 2,
    "PRICING_VARIANT": "FLAT_RISK_PREMIUM",
    "TERM_YEARS": 3,
    "NAMEPLATE_KW": 500,
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "primary_locale": DEFAULTS["LOCALE"],
    }
    defaults.update(overrides)
    return defaults


def create_engine_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": DEFAULTS["ENGINE_MODEL_CODE"],
        "manufacturer": DEFAULTS["ENGINE_MANUFACTURER"],
        "rated_kw": DEFAULTS["ENGINE_RATED_KW"],
        "fuel_burn_gph_at_75": DEFAULTS["ENGINE_BURN_GPH"],
        "emissions_tier_capability": DEFAULTS["ENGINE_TIER"],
        "list_price_cents": DEFAULTS["ENGINE_LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_alternator_model_payload(**overrides) -> dict:
    defaults = {
        "model_code": DEFAULTS["ALT_MODEL_CODE"],
        "rated_kva": DEFAULTS["ALT_RATED_KVA"],
        "efficiency_pct": DEFAULTS["ALT_EFFICIENCY_PCT"],
        "list_price_cents": DEFAULTS["ALT_LIST_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_order_payload(**overrides) -> dict:
    defaults = {
        "customer_id": None,
        "site_locale": DEFAULTS["LOCALE"],
        "occupancy_type": DEFAULTS["OCCUPANCY_TYPE"],
        "application": DEFAULTS["APPLICATION"],
    }
    defaults.update(overrides)
    return defaults


def single_step_load(kva=100, duty="CONTINUOUS", description="A"):
    return [{"description": description, "kva": kva, "duty": duty}]


def create_sizing_study_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "engine_model_id": None,
        "alternator_model_id": None,
        "load_steps": single_step_load(),
        "largest_motor_kva": DEFAULTS["LARGEST_MOTOR_KVA"],
        "starting_method": DEFAULTS["STARTING_METHOD"],
        "altitude_m": DEFAULTS["ALTITUDE_M"],
        "ambient_c": DEFAULTS["AMBIENT_C"],
        "method": DEFAULTS["SIZING_METHOD"],
        "expected_order_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_configuration_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "sizing_study_id": None,
        "enclosure_type": DEFAULTS["ENCLOSURE_TYPE"],
        "enclosure_price_cents": DEFAULTS["ENCLOSURE_PRICE_CENTS"],
        "fuel_tank_gallons": DEFAULTS["FUEL_TANK_GALLONS"],
    }
    defaults.update(overrides)
    return defaults


def create_permit_case_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "configuration_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_emissions_certificate_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "configuration_id": None,
    }
    defaults.update(overrides)
    return defaults


def create_paralleling_scheme_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "sync_mode": DEFAULTS["SYNC_MODE"],
        "max_units": DEFAULTS["MAX_UNITS"],
    }
    defaults.update(overrides)
    return defaults


def create_test_bay_payload(**overrides) -> dict:
    defaults = {
        "bay_code": DEFAULTS["BAY_CODE"],
        "max_kw": DEFAULTS["BAY_MAX_KW"],
    }
    defaults.update(overrides)
    return defaults


def create_factory_test_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "configuration_id": None,
        "bay_id": None,
        "service_date": DEFAULTS["TEST_SERVICE_DATE"],
        "start_hour": 8,
        "end_hour": 12,
    }
    defaults.update(overrides)
    return defaults


def create_crane_slot_payload(**overrides) -> dict:
    defaults = {
        "service_date": DEFAULTS["SLOT_SERVICE_DATE"],
        "window_start_hour": DEFAULTS["WINDOW_START_HOUR"],
        "window_end_hour": DEFAULTS["WINDOW_END_HOUR"],
    }
    defaults.update(overrides)
    return defaults


def create_shipment_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "crane_slot_id": None,
        "lift_start_hour": 8,
        "lift_hours": DEFAULTS["LIFT_HOURS"],
        "gross_weight_kg": DEFAULTS["GROSS_WEIGHT_KG"],
        "freight_class": DEFAULTS["FREIGHT_CLASS"],
        "expected_crane_slot_version": None,
    }
    defaults.update(overrides)
    return defaults


def create_commissioning_event_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "shipment_id": None,
        "service_date": "2026-08-20",
    }
    defaults.update(overrides)
    return defaults


def create_service_contract_payload(**overrides) -> dict:
    defaults = {
        "order_id": None,
        "pricing_variant": DEFAULTS["PRICING_VARIANT"],
        "term_years": DEFAULTS["TERM_YEARS"],
        "nameplate_kw": DEFAULTS["NAMEPLATE_KW"],
    }
    defaults.update(overrides)
    return defaults
