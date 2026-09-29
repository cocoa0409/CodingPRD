"""Payload factories: one per writable entity, input fields only."""
from typing import List, Optional

from .constants import SIZE_CURVE_TOP_4SZ, TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    payload = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "season_code": TEST_DEFAULTS["SEASON_CODE"],
        "banner_code": TEST_DEFAULTS["BANNER_CODE"],
    }
    payload.update(overrides)
    return payload


def create_store_payload(program_id: str, store_code: str = "0101", **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "store_code": store_code,
        "grade": "A",
        "grade_index_bp": 13000,
        "cluster_code": "URBAN",
        "freight_flat_usd": 41.00,
        "historical_sell_through_bp": 6500,
    }
    payload.update(overrides)
    return payload


def create_fixture_plan_payload(store_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "item_class": TEST_DEFAULTS["ITEM_CLASS"],
        "effective_from": "2026-07-01T00:00:00Z",
        "fixture_count": 4,
        "facings_per_fixture": 3,
        "units_per_facing": 4,
        "presentation_min_units": 12,
    }
    payload.update(overrides)
    return payload


def create_size_profile_payload(program_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "profile_code": TEST_DEFAULTS["PROFILE_CODE"],
        "item_class": TEST_DEFAULTS["ITEM_CLASS"],
        "size_curve": [dict(entry) for entry in SIZE_CURVE_TOP_4SZ],
    }
    payload.update(overrides)
    return payload


def create_item_payload(program_id: str, size_profile_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "sku_code": TEST_DEFAULTS["SKU_CODE"],
        "style_code": TEST_DEFAULTS["STYLE_CODE"],
        "item_class": TEST_DEFAULTS["ITEM_CLASS"],
        "item_type": "SEASONAL",
        "size_profile_id": size_profile_id,
        "unit_cost_usd": TEST_DEFAULTS["UNIT_COST_USD"],
        "retail_price_usd": TEST_DEFAULTS["RETAIL_PRICE_USD"],
    }
    payload.update(overrides)
    return payload


def create_store_position_payload(store_id: str, item_id: str, **overrides) -> dict:
    payload = {
        "store_id": store_id,
        "item_id": item_id,
        "on_hand_units": 4,
        "size_on_hand": [
            {"size_code": "S", "units": 0},
            {"size_code": "M", "units": 3},
            {"size_code": "L", "units": 1},
            {"size_code": "XL", "units": 0},
        ],
        "min_units": 12,
        "max_units": 48,
        "weekly_forecast_units": 9,
        "trailing_4wk_sales_units": 30,
    }
    payload.update(overrides)
    return payload


def create_receipt_payload(program_id: str, item_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "item_id": item_id,
        "reference": "ASN-9001",
        "units_received": 60,
        "size_received": [
            {"size_code": "S", "units": 12},
            {"size_code": "M", "units": 21},
            {"size_code": "L", "units": 18},
            {"size_code": "XL", "units": 9},
        ],
        "receipt_date": "2026-08-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def create_allocation_run_payload(expected_receipt_version: int, **overrides) -> dict:
    payload = {
        "method": "DEMAND_DRIVEN",
        "need_basis": "FORWARD_LOOKING",
        "expected_receipt_version": expected_receipt_version,
    }
    payload.update(overrides)
    return payload


def create_promo_event_payload(program_id: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "event_code": "PROMO-1",
        "scope": "PROGRAM",
        "start_date": "2026-08-10T00:00:00Z",
        "end_date": "2026-08-20T00:00:00Z",
        "lift_factor_bp": 12000,
    }
    payload.update(overrides)
    return payload


def create_transfer_payload(
    program_id: str,
    from_store_id: str,
    to_store_id: str,
    item_id: str,
    units: int,
    expected_from_position_version: int,
    **overrides,
) -> dict:
    payload = {
        "program_id": program_id,
        "from_store_id": from_store_id,
        "to_store_id": to_store_id,
        "item_id": item_id,
        "units": units,
        "expected_from_position_version": expected_from_position_version,
    }
    payload.update(overrides)
    return payload


def create_snapshot_payload(program_id: str, cluster_code: str, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "cluster_code": cluster_code,
        "basis": "UNIT_WEIGHTED",
    }
    payload.update(overrides)
    return payload


def size_map(units_by_size: dict) -> List[dict]:
    """Turn ``{"S": 4, "XL": 2}`` into the PRD's size/units array shape."""
    return [
        {"size_code": code, "units": units} for code, units in units_by_size.items()
    ]


def units_by_size(size_array: Optional[List[dict]]) -> dict:
    """Collapse a size/units array into ``{size_code: units}`` for comparison."""
    return {entry["size_code"]: entry["units"] for entry in (size_array or [])}


def shares_by_size(size_curve: Optional[List[dict]]) -> dict:
    """Collapse a size curve into ``{size_code: share_bp}``."""
    return {entry["size_code"]: entry["share_bp"] for entry in (size_curve or [])}
