"""Payload factories — one per entity, carrying only client-supplied fields."""
from .constants import TEST_DEFAULTS


def jurisdiction_payload(**overrides) -> dict:
    """A jurisdiction that requires a licence and permits limited augmentation."""
    payload = {
        "code": TEST_DEFAULTS["JURISDICTION_CODE"],
        "name": TEST_DEFAULTS["JURISDICTION_NAME"],
        "gob_license_required": True,
        "max_sale_days": 60,
        "license_cooling_off_days": 30,
        "max_augmentation_ratio": 0.1,
        "augmentation_disclosure_required": True,
        "augmentation_prohibited": False,
        "prohibited_claim_codes": [],
        "advertising_disclosure_required": False,
        "surrender_notice_days": 10,
    }
    payload.update(overrides)
    return payload


def engagement_payload(**overrides) -> dict:
    """A FEE_BASED engagement with the liquidator carrying every expense."""
    payload = {
        "retailer_name": TEST_DEFAULTS["RETAILER_NAME"],
        "liquidator_name": TEST_DEFAULTS["LIQUIDATOR_NAME"],
        "economics_model": "FEE_BASED",
        "guaranty_pct": 0,
        "hybrid_retailer_excess_pct": 0,
        "expense_responsibility": "LIQUIDATOR",
        "shared_expense_liquidator_pct": 0,
        "sale_start_date": TEST_DEFAULTS["SALE_START_DATE"],
        "target_end_date": TEST_DEFAULTS["TARGET_END_DATE"],
    }
    payload.update(overrides)
    return payload


def store_payload(jurisdiction_id, **overrides) -> dict:
    payload = {
        "jurisdiction_id": jurisdiction_id,
        "store_code": TEST_DEFAULTS["STORE_CODE"],
        "address_line": TEST_DEFAULTS["ADDRESS_LINE"],
    }
    payload.update(overrides)
    return payload


def inventory_lot_payload(**overrides) -> dict:
    """One thousand apparel units at 2000 cost / 5000 retail per unit."""
    payload = {
        "category": "APPAREL",
        "source": "ORIGINAL",
        "units_initial": 1000,
        "unit_cost_cents": 2000,
        "unit_retail_cents": 5000,
    }
    payload.update(overrides)
    return payload


def gob_license_payload(**overrides) -> dict:
    """A thirty-day licence period declaring one non-comparative claim."""
    payload = {
        "license_number": TEST_DEFAULTS["LICENSE_NUMBER"],
        "period_start_date": TEST_DEFAULTS["LICENSE_PERIOD_START"],
        "period_end_date": TEST_DEFAULTS["LICENSE_PERIOD_END"],
        "advertising_claim_codes": ["EVERYTHING_MUST_GO"],
    }
    payload.update(overrides)
    return payload


def markdown_stage_payload(expected_store_version, **overrides) -> dict:
    payload = {
        "expected_store_version": expected_store_version,
        "stage_index": 1,
        "discount_pct": 0.2,
        "sell_through_target_pct": 0.25,
        "window_start_date": "2026-09-15",
        "window_end_date": "2026-09-30",
    }
    payload.update(overrides)
    return payload


def consignment_payload(**overrides) -> dict:
    payload = {
        "supplier_name": TEST_DEFAULTS["SUPPLIER_NAME"],
        "category": "APPAREL",
        "units_supplied": 100,
        "unit_cost_cents": 1000,
        "unit_retail_cents": 3000,
        "delivery_window_start_date": "2026-09-20",
        "delivery_window_end_date": "2026-09-24",
    }
    payload.update(overrides)
    return payload


def employee_payload(**overrides) -> dict:
    payload = {
        "employee_code": "EMP-A",
        "retention_bonus_cents": 500000,
        "retention_start_date": "2026-09-15",
        "retention_target_date": "2026-11-15",
        "attendance_rate": 1.0,
    }
    payload.update(overrides)
    return payload


def sales_day_payload(**overrides) -> dict:
    payload = {
        "business_date": "2026-09-15",
        "original_net_sales_cents": 100000,
        "augmentation_net_sales_cents": 0,
        "original_units_sold": 50,
        "augmentation_units_sold": 0,
    }
    payload.update(overrides)
    return payload


def expense_item_payload(**overrides) -> dict:
    payload = {
        "expense_category": "ADVERTISING",
        "amount_cents": 100000,
        "incurred_date": "2026-09-16",
    }
    payload.update(overrides)
    return payload


def lease_disposition_payload(**overrides) -> dict:
    payload = {
        "landlord_name": TEST_DEFAULTS["LANDLORD_NAME"],
        "surrender_deadline_date": "2026-11-30",
        "daily_holdover_rate_cents": 20000,
        "rent_arrears_cents": 400000,
        "cam_arrears_cents": 150000,
        "restoration_cost_cents": 450000,
        "fixture_reserve_price_cents": 200000,
        "surrender_credit_cents": 0,
    }
    payload.update(overrides)
    return payload


def settlement_payload(expected_engagement_version, **overrides) -> dict:
    payload = {
        "settlement_basis": "PROVISIONAL",
        "expected_engagement_version": expected_engagement_version,
    }
    payload.update(overrides)
    return payload
