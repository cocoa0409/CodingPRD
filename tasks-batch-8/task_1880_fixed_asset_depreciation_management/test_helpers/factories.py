"""Payload factories — one per entity, input fields only (PRD §3, §4)."""
from .constants import DEFAULT_CLASS, TEST_DEFAULTS


def create_asset_class_payload(**overrides) -> dict:
    defaults = {
        "class_code": DEFAULT_CLASS["CLASS_CODE"],
        "name": DEFAULT_CLASS["NAME"],
        "capitalization_threshold_cents": DEFAULT_CLASS[
            "CAPITALIZATION_THRESHOLD_CENTS"
        ],
        "default_useful_life_months": DEFAULT_CLASS["DEFAULT_USEFUL_LIFE_MONTHS"],
        "book_method": DEFAULT_CLASS["BOOK_METHOD"],
        "tax_method": DEFAULT_CLASS["TAX_METHOD"],
        "bonus_depreciation_allowed": DEFAULT_CLASS["BONUS_DEPRECIATION_ALLOWED"],
    }
    defaults.update(overrides)
    return defaults


def create_capital_project_payload(asset_class_id: str, **overrides) -> dict:
    defaults = {
        "project_code": "PROJ-1",
        "name": "Capital project",
        "asset_class_id": asset_class_id,
    }
    defaults.update(overrides)
    return defaults


def create_cip_cost_line_payload(project_id: str, **overrides) -> dict:
    defaults = {
        "project_id": project_id,
        "amount_cents": 100000,
        "cost_type": "MATERIAL",
        "incurred_date": "2026-01-15",
    }
    defaults.update(overrides)
    return defaults


def create_fixed_asset_payload(asset_class_id: str, **overrides) -> dict:
    defaults = {
        "asset_tag": "A-1",
        "description": "Test asset",
        "asset_class_id": asset_class_id,
        "acquisition_cost_cents": 600000,
        "cost_center": TEST_DEFAULTS["COST_CENTER"],
        "location": TEST_DEFAULTS["LOCATION"],
    }
    defaults.update(overrides)
    return defaults


def create_depreciation_run_payload(period: str, **overrides) -> dict:
    defaults = {"period": period}
    defaults.update(overrides)
    return defaults


def create_disposal_payload(asset_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "disposal_type": "SALE",
        "proceeds_cents": 100000,
        "effective_date": "2026-03-20",
    }
    defaults.update(overrides)
    # PRD §3.5: a TRANSFER "demands `proceeds_cents` equal to zero" — the SALE
    # default of 100000 would make every factory-built TRANSFER request invalid.
    if defaults.get("disposal_type") == "TRANSFER" and "proceeds_cents" not in overrides:
        defaults["proceeds_cents"] = 0
    return defaults


def create_inventory_run_payload(**overrides) -> dict:
    defaults = {"name": "Inventory run", "scope_type": "ALL"}
    defaults.update(overrides)
    return defaults


def create_count_line_payload(asset_id: str, **overrides) -> dict:
    defaults = {
        "asset_id": asset_id,
        "found": True,
        "counted_location": TEST_DEFAULTS["LOCATION"],
    }
    defaults.update(overrides)
    return defaults


def create_impairment_review_payload(asset_id: str, **overrides) -> dict:
    defaults = {"asset_id": asset_id, "indicator": "DAMAGE"}
    defaults.update(overrides)
    return defaults


def create_external_schedule_payload(asset_id: str, **overrides) -> dict:
    """PRD §3.7: PROPERTY_TAX rows carry assessed_value_cents; INSURANCE rows
    carry annual_premium_cents. The payloads are kept mutually exclusive."""
    defaults = {
        "asset_id": asset_id,
        "schedule_type": "PROPERTY_TAX",
        "schedule_year": 2026,
        "assessed_value_cents": 8000000,
    }
    defaults.update(overrides)
    if defaults.get("schedule_type") == "INSURANCE":
        defaults.pop("assessed_value_cents", None)
        defaults.setdefault("annual_premium_cents", 120000)
    return defaults
