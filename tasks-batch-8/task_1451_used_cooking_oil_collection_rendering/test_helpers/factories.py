"""Payload factories — one per entity, input fields only (PRD §3/§4)."""

DEFAULTS = {
    "CUSTOMER_NAME": "Test Site",
    "SITE_ADDRESS": "1 Fry Way",
    "SITE_MAX_CONTAINER_GAL": 5000,
    "PRICING_MODE": "REBATE",
    "INDEX_CODE": "YG_CBI",
    "TERM_START": "2026-07-01",
    "TERM_END": "2027-07-01",
    "FLOOR_CENTS_PER_GAL": 50,
    "CAP_CENTS_PER_GAL": 150,
    "CONTAINER_CAPACITY_GAL": 300,
    "CONTAINER_FILL_RATE": 100,
    "LOCK_CODE": "LK1",
    "TRUCK_PLATE": "T-1",
    "TANK_CAPACITY_GAL": 500,
    "DRIVER_REF": "drv-1",
    "SERVICE_DATE": "2026-08-05",
    "PUMP_GALLONS": 100.00,
    "FIELD_MOISTURE_PCT": 5.0,
    "QUOTE_WEEK_START": "2026-08-03",
    "QUOTE_PRICE_CENTS": 100,
    "PERIOD_START": "2026-08-01",
    "PERIOD_END": "2026-08-15",
}


def create_customer_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["CUSTOMER_NAME"],
        "site_address": DEFAULTS["SITE_ADDRESS"],
        "site_max_container_gal": DEFAULTS["SITE_MAX_CONTAINER_GAL"],
    }
    defaults.update(overrides)
    return defaults


def create_contract_payload(**overrides) -> dict:
    defaults = {
        "pricing_mode": DEFAULTS["PRICING_MODE"],
        "index_code": DEFAULTS["INDEX_CODE"],
        "term_start": DEFAULTS["TERM_START"],
        "term_end": DEFAULTS["TERM_END"],
        "floor_cents_per_gal": DEFAULTS["FLOOR_CENTS_PER_GAL"],
        "cap_cents_per_gal": DEFAULTS["CAP_CENTS_PER_GAL"],
    }
    defaults.update(overrides)
    return defaults


def create_container_payload(**overrides) -> dict:
    defaults = {
        "capacity_gallons": DEFAULTS["CONTAINER_CAPACITY_GAL"],
        "est_fill_rate_gal_per_week": DEFAULTS["CONTAINER_FILL_RATE"],
        "lock_code": DEFAULTS["LOCK_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(**overrides) -> dict:
    defaults = {
        "plate": DEFAULTS["TRUCK_PLATE"],
        "tank_capacity_gallons": DEFAULTS["TANK_CAPACITY_GAL"],
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(**overrides) -> dict:
    defaults = {
        "truck_id": DEFAULTS["TRUCK_PLATE"],
        "driver_ref": DEFAULTS["DRIVER_REF"],
        "service_date": DEFAULTS["SERVICE_DATE"],
        "container_ids": [],
    }
    defaults.update(overrides)
    return defaults


def complete_visit_payload(**overrides) -> dict:
    defaults = {
        "pump_gallons": DEFAULTS["PUMP_GALLONS"],
        "field_moisture_pct": DEFAULTS["FIELD_MOISTURE_PCT"],
    }
    defaults.update(overrides)
    return defaults


def grade_sample_payload(**overrides) -> dict:
    defaults = {
        "lab_moisture_pct": 10.0,
        "lab_impurity_pct": 1.0,
    }
    defaults.update(overrides)
    return defaults


def create_quote_payload(**overrides) -> dict:
    defaults = {
        "index_code": DEFAULTS["INDEX_CODE"],
        "week_start": DEFAULTS["QUOTE_WEEK_START"],
        "price_cents_per_gal": DEFAULTS["QUOTE_PRICE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def generate_settlement_payload(**overrides) -> dict:
    defaults = {
        "customer_id": "",
        "period_start": DEFAULTS["PERIOD_START"],
        "period_end": DEFAULTS["PERIOD_END"],
    }
    defaults.update(overrides)
    return defaults


def create_complaint_payload(**overrides) -> dict:
    defaults = {
        "customer_id": "",
        "category": "ODOR",
        "severity": "LOW",
        "note": "test complaint",
    }
    defaults.update(overrides)
    return defaults


def create_theft_incident_payload(**overrides) -> dict:
    defaults = {
        "container_id": "",
        "evidence_note": "lock cut",
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(**overrides) -> dict:
    defaults = {
        "manifest_id": "",
        "input_gallons": 0,
    }
    defaults.update(overrides)
    return defaults
