"""Payload factories — one per entity, input fields only.

Defaults come from the canonical scenario constants; every factory accepts
**overrides so tests control exactly the values their claim needs.
"""
from .constants import ALT_104_UNIT_COST_CENTS, ALT_104_UNIT_RETAIL_CENTS


def create_fleet_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": "HaulCo",
        "account_number": "ACCT-1001",
        "billing_email": "ap@haulco.example",
        "per_call_authorization_limit_cents": 100000,
        "monthly_spend_cap_cents": 500000,
    }
    defaults.update(overrides)
    return defaults


def create_rate_card_payload(**overrides) -> dict:
    from .constants import STD_CARD
    defaults = dict(STD_CARD)
    defaults.update(overrides)
    return defaults


def create_vehicle_payload(**overrides) -> dict:
    defaults = {
        "vin": "1FUJHHDR1LLLW0002",
        "unit_number": "R-01",
        "make": "Kenworth",
        "model": "T680",
        "year": 2020,
        "odometer_miles": 90000,
    }
    defaults.update(overrides)
    return defaults


def create_technician_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Tom Standard",
        "employee_code": "T-101",
        "certifications": ["ENGINE"],
        "labor_rate_class": "STANDARD",
        "home_depot_city": "Denver",
    }
    defaults.update(overrides)
    return defaults


def create_van_stock_payload(**overrides) -> dict:
    defaults = {
        "part_number": "ALT-104",
        "description": "Alternator",
        "part_class": "ENGINE",
        "qty_on_hand": 10,
        "unit_cost_cents": ALT_104_UNIT_COST_CENTS,
        "unit_retail_cents": ALT_104_UNIT_RETAIL_CENTS,
    }
    defaults.update(overrides)
    return defaults


def create_service_call_payload(vehicle_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "caller_name": "Jo",
        "caller_phone": "555-0111",
        "breakdown_location_text": "US-6 mm 12",
        "distance_miles_from_depot": 20,
        "symptom_category": "ENGINE_NO_START",
        "symptom_description": "no start",
    }
    defaults.update(overrides)
    return defaults


def create_dispatch_payload(technician_id, expected_service_call_version,
                            **overrides) -> dict:
    defaults = {
        "technician_id": technician_id,
        "window_start_at": "2026-08-05T09:00:00Z",
        "window_end_at": "2026-08-05T13:00:00Z",
        "planned_travel_miles": 20,
        "expected_service_call_version": expected_service_call_version,
    }
    defaults.update(overrides)
    return defaults


def create_estimate_payload(expected_service_call_version, **overrides) -> dict:
    defaults = {
        "labor_hours_est": 1.0,
        "travel_miles_est": 20,
        "parts_estimate_cents": 30000,
        "expected_service_call_version": expected_service_call_version,
    }
    defaults.update(overrides)
    return defaults


def create_part_usage_payload(van_stock_item_id, **overrides) -> dict:
    defaults = {
        "van_stock_item_id": van_stock_item_id,
        "qty": 1,
    }
    defaults.update(overrides)
    return defaults


def create_tow_order_payload(**overrides) -> dict:
    defaults = {
        "tow_provider_name": "HeavyHaul",
        "tow_unit_id": "TT-7",
        "pickup_location_text": "site A",
        "dropoff_location_text": "dealer Denver",
        "pickup_window_start_at": "2026-08-05T10:00:00Z",
        "pickup_window_end_at": "2026-08-05T12:00:00Z",
        "tow_fee_cents": 85000,
    }
    defaults.update(overrides)
    return defaults


def create_warranty_claim_payload(**overrides) -> dict:
    defaults = {
        "claim_type": "OEM_BASE",
        "oem_labor_hours": 1.8,
        "oem_labor_rate_cents": 12000,
        "parts_at_cost_cents": 42000,
    }
    defaults.update(overrides)
    return defaults


def create_inspection_defect_payload(**overrides) -> dict:
    defaults = {
        "source": "ROADSIDE_DOT_INSPECTION",
        "defect_code": "393.9",
        "severity": "OOS",
        "discovered_at": "2026-08-05T08:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(**overrides) -> dict:
    defaults = {
        "amount_cents": 1000,
        "method": "CARD",
    }
    defaults.update(overrides)
    return defaults


def create_repeat_failure_case_payload(vehicle_id, original_service_call_id,
                                       new_service_call_id, **overrides) -> dict:
    defaults = {
        "vehicle_id": vehicle_id,
        "original_service_call_id": original_service_call_id,
        "new_service_call_id": new_service_call_id,
    }
    defaults.update(overrides)
    return defaults
