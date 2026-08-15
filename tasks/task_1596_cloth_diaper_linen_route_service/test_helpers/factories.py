"""Payload factories — one per creatable resource, input fields only.

Computed and system-managed fields (PRD 2.4) are never supplied here.
"""
import itertools
from typing import Any, Dict, Optional

from .constants import (
    DEFAULT_WINDOW_END_MINUTES,
    DEFAULT_WINDOW_START_MINUTES,
    STANDARD_PLAN,
    ZONE_NORTH_WEEKDAYS,
)

_counter = itertools.count(1)


def unique_email() -> str:
    return f"customer-{next(_counter)}@example.com"


def unique_code(prefix: str) -> str:
    return f"{prefix}-{next(_counter)}"


def create_plan_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = dict(STANDARD_PLAN)
    defaults["tier_code"] = overrides.pop("tier_code", unique_code("TIER"))
    defaults.update(overrides)
    return defaults


def create_zone_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "zone_code": unique_code("Z"),
        "service_weekdays": list(ZONE_NORTH_WEEKDAYS),
        "stop_cutoff_hours": 24,
        "active": True,
    }
    defaults.update(overrides)
    return defaults


def create_customer_payload(zone_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "full_name": "Test Customer",
        "email": unique_email(),
        "service_zone_id": zone_id,
        "child_birthdate": "2026-01-15",
        "child_size_code": "MEDIUM",
    }
    defaults.update(overrides)
    return defaults


def create_subscription_payload(
    customer_id: str, plan_id: str, zone_id: str, **overrides: Any
) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "customer_id": customer_id,
        "subscription_plan_id": plan_id,
        "service_zone_id": zone_id,
        "start_date": "2026-08-01",
        "current_size_code": "MEDIUM",
        "window_start_minutes": DEFAULT_WINDOW_START_MINUTES,
        "window_end_minutes": DEFAULT_WINDOW_END_MINUTES,
    }
    defaults.update(overrides)
    return defaults


def create_pause_payload(
    subscription_id: str,
    start_date: str,
    end_date: str,
    expected_subscription_version: int,
) -> Dict[str, Any]:
    return {
        "subscription_id": subscription_id,
        "start_date": start_date,
        "end_date": end_date,
        "expected_subscription_version": expected_subscription_version,
    }


def create_route_payload(zone_id: str, route_date: str) -> Dict[str, Any]:
    return {"service_zone_id": zone_id, "route_date": route_date}


def create_route_stop_payload(
    route_id: str,
    subscription_id: str,
    window_start_minutes: int,
    window_end_minutes: int,
) -> Dict[str, Any]:
    return {
        "route_id": route_id,
        "subscription_id": subscription_id,
        "window_start_minutes": window_start_minutes,
        "window_end_minutes": window_end_minutes,
    }


def complete_stop_payload(
    clean_items_delivered: int,
    soiled_bags_collected: int,
    expected_route_version: int,
) -> Dict[str, Any]:
    return {
        "soiled_bags_collected": soiled_bags_collected,
        "clean_items_delivered": clean_items_delivered,
        "expected_route_version": expected_route_version,
    }


def create_intake_payload(
    route_stop_id: str, scale_weight_g: int, soil_level: str = "NORMAL"
) -> Dict[str, Any]:
    return {
        "route_stop_id": route_stop_id,
        "scale_weight_g": scale_weight_g,
        "soil_level": soil_level,
    }


def create_formula_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "formula_code": unique_code("F"),
        "base_detergent_ml_per_kg": 45,
        "sanitizer_ml_per_kg": 8,
        "min_temp_celsius": 71,
        "min_dwell_seconds": 180,
        "chlorine_ppm_min": 50,
        "chlorine_ppm_max": 200,
        "max_rewash_count": 2,
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(
    formula_id: str, soil_level: str = "HEAVY", water_hardness: str = "HARD"
) -> Dict[str, Any]:
    return {
        "wash_formula_id": formula_id,
        "soil_level": soil_level,
        "water_hardness": water_hardness,
    }


def create_pool_payload(size_code: str = "MEDIUM") -> Dict[str, Any]:
    return {"size_code": size_code}


def pool_adjustment_payload(adjustment_type: str, units: int) -> Dict[str, Any]:
    return {"adjustment_type": adjustment_type, "units": units}


def create_swap_payload(subscription_id: str, to_size_code: str) -> Dict[str, Any]:
    return {"subscription_id": subscription_id, "to_size_code": to_size_code}


def create_case_payload(
    subscription_id: str,
    pool_id: str,
    case_type: str = "LOST",
    item_count: int = 1,
    first_issued_date: str = "2026-06-01",
    assessed_fee_cents: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subscription_id": subscription_id,
        "inventory_pool_id": pool_id,
        "case_type": case_type,
        "item_count": item_count,
        "first_issued_date": first_issued_date,
    }
    if assessed_fee_cents is not None:
        payload["assessed_fee_cents"] = assessed_fee_cents
    return payload


def generate_invoice_payload(
    subscription_id: str,
    period_start: str = "2026-08-03",
    period_end: str = "2026-08-10",
) -> Dict[str, Any]:
    return {
        "subscription_id": subscription_id,
        "period_start": period_start,
        "period_end": period_end,
    }
