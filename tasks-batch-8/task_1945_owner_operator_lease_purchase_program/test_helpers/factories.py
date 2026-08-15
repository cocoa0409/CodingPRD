"""Payload factories — one per entity, input fields only (PRD section 4)."""

import uuid

from .constants import TEST_DEFAULTS


def _uniq(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def create_owner_operator_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Pat Owner",
        "cdl_number": _uniq("CDL"),
    }
    defaults.update(overrides)
    return defaults


def create_truck_payload(**overrides) -> dict:
    defaults = {
        "vin": _uniq("VIN"),
        "year": 2023,
        "make": "Freightliner",
        "model": "Cascadia",
        "odometer_current": 50000,
        "powertrain_warranty_expires_on": "2027-01-01",
        "powertrain_warranty_mileage_limit": 100000,
    }
    defaults.update(overrides)
    return defaults


def create_lease_payload(owner_operator_id: str, truck_id: str, **overrides) -> dict:
    defaults = {
        "owner_operator_id": owner_operator_id,
        "truck_id": truck_id,
        "start_date": TEST_DEFAULTS["START_DATE"],
        "term_weeks": TEST_DEFAULTS["TERM_WEEKS"],
        "weekly_payment_cents": TEST_DEFAULTS["WEEKLY_PAYMENT_CENTS"],
        "escrow_weekly_contribution_cents": TEST_DEFAULTS["ESCROW_WEEKLY_CONTRIBUTION_CENTS"],
        "escrow_cap_cents": TEST_DEFAULTS["ESCROW_CAP_CENTS"],
        "buyout_base_price_cents": TEST_DEFAULTS["BUYOUT_BASE_PRICE_CENTS"],
        "min_revenue_guarantee_weekly_cents": TEST_DEFAULTS["MIN_REVENUE_GUARANTEE_WEEKLY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_settlement_payload(lease_id: str, week_start_date: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "week_start_date": week_start_date,
        "gross_revenue_cents": 250000,
        "fuel_gallons": 200,
        "fuel_price_cents_per_gallon": 350,
        "insurance_weekly_cents": 22000,
        "miles_driven": 2500,
        "load_declined_flag": False,
    }
    defaults.update(overrides)
    return defaults


def create_lane_payload(lease_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "origin": "ATL",
        "destination": "DAL",
        "weekly_commitment_cents": 120000,
        "start_date": "2026-08-03",
        "end_date": "2026-10-26",
    }
    defaults.update(overrides)
    return defaults


def create_service_bay_payload(**overrides) -> dict:
    defaults = {
        "bay_code": _uniq("BAY"),
        "location": "Terminal 1",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(lease_id: str, service_bay_id: str, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "service_bay_id": service_bay_id,
        "category": "PREVENTIVE",
        "description": "Scheduled service",
        "scheduled_start": "2026-08-04T08:00:00Z",
        "scheduled_end": "2026-08-04T09:00:00Z",
        "estimated_cost_cents": 30000,
    }
    defaults.update(overrides)
    return defaults


def create_compliance_document_payload(owner_operator_id: str, doc_type: str, **overrides) -> dict:
    defaults = {
        "owner_operator_id": owner_operator_id,
        "doc_type": doc_type,
        "expires_on": "2027-08-01",
    }
    defaults.update(overrides)
    return defaults


def create_buyout_quote_payload(lease_id: str, quote_kind: str, expected_lease_version: int, **overrides) -> dict:
    defaults = {
        "lease_id": lease_id,
        "quote_kind": quote_kind,
        "expected_lease_version": expected_lease_version,
    }
    defaults.update(overrides)
    return defaults
