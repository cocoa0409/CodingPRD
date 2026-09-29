"""Payload factories — one per resource, carrying only client-supplied fields."""
import itertools

from .constants import CANONICAL, CANONICAL_SIZE_CURVE

_seq = itertools.count(1)


def unique_suffix() -> str:
    """Short unique suffix for codes that must be unique."""
    return f"{next(_seq):02d}"


def department_payload(**overrides) -> dict:
    payload = dict(CANONICAL["department"])
    payload.update(overrides)
    return payload


def category_payload(department_id: str, **overrides) -> dict:
    payload = {"department_id": department_id}
    payload.update(CANONICAL["category"])
    payload.update(overrides)
    return payload


def store_cluster_payload(**overrides) -> dict:
    payload = dict(CANONICAL["store_cluster"])
    payload.update(overrides)
    return payload


def vendor_payload(**overrides) -> dict:
    payload = dict(CANONICAL["vendor"])
    payload.update(overrides)
    return payload


def vendor_authorization_payload(vendor_id: str, category_id: str, **overrides) -> dict:
    payload = {
        "vendor_id": vendor_id,
        "category_id": category_id,
        "max_open_units": CANONICAL["max_open_units"],
    }
    payload.update(overrides)
    return payload


def category_plan_payload(category_id: str, **overrides) -> dict:
    payload = {"category_id": category_id}
    payload.update(CANONICAL["category_plan"])
    payload.update(overrides)
    return payload


def plan_month_payload(category_plan_id: str, **overrides) -> dict:
    payload = {"category_plan_id": category_plan_id}
    payload.update(CANONICAL["month_1"])
    payload.update(overrides)
    return payload


def option_plan_payload(category_plan_id: str, store_cluster_id: str, **overrides) -> dict:
    payload = {
        "category_plan_id": category_plan_id,
        "store_cluster_id": store_cluster_id,
    }
    payload.update(CANONICAL["option_plan"])
    payload.update(overrides)
    return payload


def size_curve_payload(cells=None) -> dict:
    return {"cells": [dict(c) for c in (cells or CANONICAL_SIZE_CURVE)]}


def assortment_item_payload(option_plan_id: str, vendor_id: str, **overrides) -> dict:
    payload = {
        "option_plan_id": option_plan_id,
        "vendor_id": vendor_id,
        "sku_code": f"DRSS-SKU-{unique_suffix()}",
        "color_code": "BLK",
        "lifecycle_stage": "CARRYOVER",
        "unit_cost_cents": 2500,
        "retail_price_cents": 6900,
        "prior_season_sell_through_bps": 7100,
    }
    payload.update(overrides)
    return payload


def receipt_commitment_payload(
    plan_month_id: str,
    assortment_item_id: str,
    vendor_id: str,
    expected_plan_month_version: int,
    **overrides,
) -> dict:
    payload = {
        "plan_month_id": plan_month_id,
        "assortment_item_id": assortment_item_id,
        "vendor_id": vendor_id,
        "units": 400,
        "unit_cost_cents": 2500,
        "ship_window_start": "2027-03-05T00:00:00Z",
        "ship_window_end": "2027-03-19T00:00:00Z",
        "expected_plan_month_version": expected_plan_month_version,
    }
    payload.update(overrides)
    return payload


def actuals_post_payload(plan_month_id: str, week_index: int = 1, **overrides) -> dict:
    payload = {
        "plan_month_id": plan_month_id,
        "week_index": week_index,
        "actual_sales_cents": 7_500_000,
        "actual_receipts_cents": 6_000_000,
        "actual_units_received": 2500,
    }
    payload.update(overrides)
    return payload


def reforecast_payload(expected_category_plan_version: int, **overrides) -> dict:
    payload = {
        "reason_note": "in-season correction requested",
        "expected_category_plan_version": expected_category_plan_version,
    }
    payload.update(overrides)
    return payload


def chase_cancel_decision_payload(
    reforecast_cycle_id: str, assortment_item_id: str, **overrides
) -> dict:
    payload = {
        "reforecast_cycle_id": reforecast_cycle_id,
        "assortment_item_id": assortment_item_id,
        "action": "CHASE",
        "requested_units": 500,
        "rationale": "trading ahead of plan on this option",
    }
    payload.update(overrides)
    return payload


def localization_overlay_payload(
    category_plan_id: str, store_cluster_id: str, **overrides
) -> dict:
    payload = {
        "category_plan_id": category_plan_id,
        "store_cluster_id": store_cluster_id,
        "overlay_type": "CLIMATE",
        "effective_start": "2026-08-05T00:00:00Z",
        "effective_end": "2026-08-31T00:00:00Z",
        "unit_multiplier_bps": 11000,
    }
    payload.update(overrides)
    return payload
