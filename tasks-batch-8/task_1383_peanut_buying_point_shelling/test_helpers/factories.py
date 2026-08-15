"""Payload factories — one per entity, input fields only."""
from .constants import (
    STANDARD_DAMAGE_RATE_CENTS_PER_PCT,
    STANDARD_FM_TIERS,
    STANDARD_MOISTURE_TIERS,
    TEST_DEFAULTS,
)


def create_buying_point_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["BP_NAME"],
        "crop_year": TEST_DEFAULTS["CROP_YEAR"],
        "drying_rate_per_cycle_cents": TEST_DEFAULTS["DRYING_RATE_PER_CYCLE_CENTS"],
        "quota_price_cents_per_ton": TEST_DEFAULTS["QUOTA_PRICE_CENTS_PER_TON"],
        "additional_price_cents_per_ton": TEST_DEFAULTS["ADDITIONAL_PRICE_CENTS_PER_TON"],
        "loan_rate_quota_cents_per_ton": TEST_DEFAULTS["LOAN_RATE_QUOTA_CENTS_PER_TON"],
        "loan_rate_additional_cents_per_ton": TEST_DEFAULTS["LOAN_RATE_ADDITIONAL_CENTS_PER_TON"],
    }
    defaults.update(overrides)
    return defaults


def create_grower_payload(**overrides) -> dict:
    defaults = {"name": "Grower One", "farm_number": "F-1001"}
    defaults.update(overrides)
    return defaults


def create_discount_schedule_payload(**overrides) -> dict:
    defaults = {
        "schedule_code": "FALL-2026",
        "effective_from": "2026-08-01T00:00:00Z",
        "effective_to": "2027-01-01T00:00:00Z",
        "moisture_tiers": STANDARD_MOISTURE_TIERS,
        "foreign_material_tiers": STANDARD_FM_TIERS,
        "damage_rate_cents_per_pct": STANDARD_DAMAGE_RATE_CENTS_PER_PCT,
    }
    defaults.update(overrides)
    return defaults


def create_load_payload(**overrides) -> dict:
    defaults = {"grower_id": None, "crop_year": TEST_DEFAULTS["CROP_YEAR"]}
    defaults.update(overrides)
    return {k: v for k, v in defaults.items() if v is not None}


def create_grade_sheet_payload(expected_farmer_stock_load_version, **overrides) -> dict:
    defaults = {
        "moisture_pct": 9.2,
        "foreign_material_pct": 5.5,
        "damage_pct": 2.0,
        "lsk_pct": 1.0,
        "expected_farmer_stock_load_version": expected_farmer_stock_load_version,
    }
    defaults.update(overrides)
    return defaults


def create_aflatoxin_certificate_payload(**overrides) -> dict:
    defaults = {"sample_ref": "SAMP-A1"}
    defaults.update(overrides)
    return defaults


def create_dryer_payload(**overrides) -> dict:
    defaults = {
        "buying_point_id": None,
        "name": "D1",
        "cycle_capacity_tons": 12,
        "cycle_hours": 6,
    }
    defaults.update(overrides)
    return defaults


def create_dryer_booking_payload(**overrides) -> dict:
    defaults = {"dryer_id": None, "load_id": None, "tons": 24.0,
                "starts_at": "2026-09-03T06:00:00Z"}
    defaults.update(overrides)
    return defaults


def create_warehouse_payload(**overrides) -> dict:
    defaults = {
        "buying_point_id": None,
        "name": "WH-G",
        "compartment": "GENERAL",
        "capacity_tons": 2000,
    }
    defaults.update(overrides)
    return defaults


def create_storage_receipt_payload(**overrides) -> dict:
    defaults = {"load_id": None, "warehouse_id": None}
    defaults.update(overrides)
    return defaults


def create_loan_pledge_payload(**overrides) -> dict:
    defaults = {
        "grower_id": None,
        "storage_receipt_id": None,
        "pledged_tons": 25.0,
        "maturity_date": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_sheller_contract_payload(**overrides) -> dict:
    defaults = {
        "buying_point_id": None,
        "sheller_ref": "sheller-acme",
        "total_units_tons": 40.0,
        "price_per_ton_cents": 61000,
        "accepts_segregated": False,
        "window_start": "2026-09-01T00:00:00Z",
        "window_end": "2026-11-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_delivery_call_payload(**overrides) -> dict:
    defaults = {
        "contract_id": None,
        "requested_tons": 20.0,
        "dock_window_start": "2026-09-10T08:00:00Z",
        "dock_window_end": "2026-09-10T12:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_quota_history_payload(**overrides) -> dict:
    defaults = {"grower_id": None, "crop_year": TEST_DEFAULTS["CROP_YEAR"],
                "quota_tons": 100}
    defaults.update(overrides)
    return defaults


def compute_settlement_payload(expected_grower_version, **overrides) -> dict:
    defaults = {
        "crop_year": TEST_DEFAULTS["CROP_YEAR"],
        "expected_grower_version": expected_grower_version,
    }
    defaults.update(overrides)
    return defaults
