"""Payload factories — one per entity, input fields only.

Field names are exactly as the PRD names them. Optional input fields are only
included when an override supplies them (so omission paths can be tested).
"""

DEFAULTS = {
    "VARIETY_COMMON_NAME": "Test Variety",
    "CULTIVAR_CODE": "TESTVAR1",
    "PROPAGATION_FORM": "PLUG",
    "GROW_CYCLE_DAYS": 5,
    "CONTAINER_FOOTPRINT_UNITS": 1,
    "SHIP_READY_GRADE_MIN_HEIGHT_CM": 8,
    "SHIP_READY_MIN_LIVE_PCT": 0.5,
    "ZONE_NAME": "Test Zone",
    "CLIMATE_CLASS": "MIXED",
    "CAPACITY_UNITS": 3000,
    "SOURCE_SUPPLIER": "PlugCo",
    "SOURCED_COUNT": 100,
    "BROKER_COMPANY": "Test Broker",
    "BROKER_EMAIL": "broker@example.com",
    "SHIP_TO_STATE": "OR",
    "CREDIT_LIMIT_CENTS": 5_000_000,
    "UNIT_PRICE_CENTS": 300,
    "REQUESTED_SHIP_DATE": "2026-03-01T00:00:00Z",
    "ORIGIN_STATE": "OR",
    "VALID_UNTIL": "2026-12-31T00:00:00Z",
}


def create_variety_payload(**overrides) -> dict:
    payload = {
        "common_name": DEFAULTS["VARIETY_COMMON_NAME"],
        "cultivar_code": DEFAULTS["CULTIVAR_CODE"],
        "propagation_form": DEFAULTS["PROPAGATION_FORM"],
        "grow_cycle_days": DEFAULTS["GROW_CYCLE_DAYS"],
        "container_footprint_units": DEFAULTS["CONTAINER_FOOTPRINT_UNITS"],
        "ship_ready_grade_min_height_cm": DEFAULTS["SHIP_READY_GRADE_MIN_HEIGHT_CM"],
        "ship_ready_min_live_pct": DEFAULTS["SHIP_READY_MIN_LIVE_PCT"],
    }
    payload.update(overrides)
    return payload


def create_zone_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["ZONE_NAME"],
        "climate_class": DEFAULTS["CLIMATE_CLASS"],
        "capacity_units": DEFAULTS["CAPACITY_UNITS"],
    }
    payload.update(overrides)
    return payload


def create_batch_payload(**overrides) -> dict:
    payload = {
        "source_supplier": DEFAULTS["SOURCE_SUPPLIER"],
        "sourced_count": DEFAULTS["SOURCED_COUNT"],
    }
    payload.update(overrides)
    return payload


def create_input_log_payload(event_type, **overrides) -> dict:
    payload = {"event_type": event_type}
    payload.update(overrides)
    return payload


def create_broker_payload(**overrides) -> dict:
    payload = {
        "company_name": DEFAULTS["BROKER_COMPANY"],
        "contact_email": DEFAULTS["BROKER_EMAIL"],
        "ship_to_state": DEFAULTS["SHIP_TO_STATE"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
    }
    payload.update(overrides)
    return payload


def create_availability_payload(**overrides) -> dict:
    payload = {"unit_price_cents": DEFAULTS["UNIT_PRICE_CENTS"]}
    payload.update(overrides)
    return payload


def create_order_payload(**overrides) -> dict:
    payload = {"requested_ship_date": DEFAULTS["REQUESTED_SHIP_DATE"]}
    payload.update(overrides)
    return payload


def create_order_line_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def create_phyto_payload(**overrides) -> dict:
    payload = {
        "origin_state": DEFAULTS["ORIGIN_STATE"],
        "valid_until": DEFAULTS["VALID_UNTIL"],
    }
    payload.update(overrides)
    return payload
