"""Payload factories — one per creatable entity, input fields only (PRD §3, §4)."""
import uuid

DEFAULTS = {
    "COMPANY_NAME": "Test Contractor Co",
    "CREDIT_LIMIT_CENTS": 5_000_000,
    "DEFAULT_WASTE_PCT_BP": 0,
    "BOARD_KIND": "REGULAR",
    "LENGTH_FT": 8,
    "WIDTH_FT": 4,
    "THICKNESS_IN": "1/2",
    "SHEETS_PER_BUNDLE": 20,
    "UNIT_PRICE_CENTS_PER_SHEET": 1500,
    "LEAD_TIME_DAYS": 0,
    "MAX_BUNDLE_CAPACITY": 100,
    "MAX_WEIGHT_LBS": 100000,
    "JOBSITE_NAME": "Jobsite P",
    "DISTANCE_MILES": 10,
    "FRAMING_PCT_COMPLETE": 60,
    "SHEET_COUNT": 20,
    "SCHEDULED_DATE": "2026-08-02",
    "SHIFT_WINDOW": "AM",
    "FLOOR_LABEL": "L1",
    "ROOM_LABEL": "101",
    "BUNDLE_COUNT": 1,
    "PAYMENT_METHOD": "ACH",
    "RECEIVED_AT": "2026-08-03T00:00:00Z",
}


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def create_contractor_account_payload(**overrides) -> dict:
    defaults = {
        "company_name": DEFAULTS["COMPANY_NAME"],
        "credit_limit_cents": DEFAULTS["CREDIT_LIMIT_CENTS"],
        "default_waste_pct_bp": DEFAULTS["DEFAULT_WASTE_PCT_BP"],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(**overrides) -> dict:
    defaults = {
        "sku": _unique("SKU"),
        "board_kind": DEFAULTS["BOARD_KIND"],
        "length_ft": DEFAULTS["LENGTH_FT"],
        "width_ft": DEFAULTS["WIDTH_FT"],
        "thickness_in": DEFAULTS["THICKNESS_IN"],
        "sheets_per_bundle": DEFAULTS["SHEETS_PER_BUNDLE"],
        "unit_price_cents_per_sheet": DEFAULTS["UNIT_PRICE_CENTS_PER_SHEET"],
        "lead_time_days": DEFAULTS["LEAD_TIME_DAYS"],
    }
    defaults.update(overrides)
    return defaults


def create_boom_truck_payload(**overrides) -> dict:
    defaults = {
        "truck_code": _unique("BT"),
        "max_bundle_capacity": DEFAULTS["MAX_BUNDLE_CAPACITY"],
        "max_weight_lbs": DEFAULTS["MAX_WEIGHT_LBS"],
    }
    defaults.update(overrides)
    return defaults


def create_project_payload(account_id: str, **overrides) -> dict:
    defaults = {
        "account_id": account_id,
        "jobsite_name": DEFAULTS["JOBSITE_NAME"],
        "distance_miles": DEFAULTS["DISTANCE_MILES"],
        "framing_pct_complete": DEFAULTS["FRAMING_PCT_COMPLETE"],
    }
    defaults.update(overrides)
    return defaults


def create_takeoff_payload(project_id: str, **overrides) -> dict:
    defaults = {"project_id": project_id}
    defaults.update(overrides)
    return defaults


def create_takeoff_line_payload(product_id: str, sheet_count: int = None, **overrides) -> dict:
    defaults = {
        "product_id": product_id,
        "sheet_count": sheet_count if sheet_count is not None else DEFAULTS["SHEET_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_stocking_order_payload(project_id: str, takeoff_id: str, boom_truck_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "takeoff_id": takeoff_id,
        "scheduled_date": DEFAULTS["SCHEDULED_DATE"],
        "shift_window": DEFAULTS["SHIFT_WINDOW"],
        "boom_truck_id": boom_truck_id,
    }
    defaults.update(overrides)
    return defaults


def create_stocking_drop_payload(product_id: str, **overrides) -> dict:
    defaults = {
        "floor_label": DEFAULTS["FLOOR_LABEL"],
        "room_label": DEFAULTS["ROOM_LABEL"],
        "product_id": product_id,
        "bundle_count": DEFAULTS["BUNDLE_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_payment_payload(amount_cents: int, **overrides) -> dict:
    defaults = {
        "amount_cents": amount_cents,
        "method": DEFAULTS["PAYMENT_METHOD"],
        "received_at": DEFAULTS["RECEIVED_AT"],
    }
    defaults.update(overrides)
    return defaults


def create_bundle_return_payload(stocking_order_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "stocking_order_id": stocking_order_id,
        "product_id": product_id,
        "bundles_returned": 1,
        "loose_sheets_returned": 0,
    }
    defaults.update(overrides)
    return defaults


def create_lock_payload(expected_takeoff_version: int) -> dict:
    return {"expected_takeoff_version": expected_takeoff_version}
