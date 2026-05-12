"""Payload factories — one factory per entity, input fields only.

Field names match PRD §3 verbatim. Every factory accepts **overrides so
individual tests can pin specific values for boundary or precondition
behavior.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers for unique inputs
# ---------------------------------------------------------------------------
def unique_store_code(prefix: str = "S") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def unique_recipe_code(prefix: str = "R") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def unique_ingredient_sku(prefix: str = "I") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def unique_vehicle_code(prefix: str = "V") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def unique_user_id(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def unique_name(prefix: str = "Name") -> str:
    return f"{prefix} {uuid.uuid4().hex[:6]}"


# ---------------------------------------------------------------------------
# Store payload (PRD §3.1)
# ---------------------------------------------------------------------------
def create_store_payload(
    *,
    store_code: Optional[str] = None,
    name: Optional[str] = None,
    temperature_zone: str = "MIXED",
    catalog_permission: Optional[List[str]] = None,
    order_window_open_minute: int = 0,
    order_window_close_minute: int = 1439,
    cutoff_minutes_before_close: Optional[int] = None,
    low_amount_bypass_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "store_code": store_code or unique_store_code(),
        "name": name or unique_name("Store"),
        "temperature_zone": temperature_zone,
        "catalog_permission": (
            catalog_permission if catalog_permission is not None else []
        ),
        "order_window_open_minute": order_window_open_minute,
        "order_window_close_minute": order_window_close_minute,
    }
    if cutoff_minutes_before_close is not None:
        payload["cutoff_minutes_before_close"] = cutoff_minutes_before_close
    if low_amount_bypass_cents is not None:
        payload["low_amount_bypass_cents"] = low_amount_bypass_cents
    payload.update(overrides)
    return payload


def patch_store_payload(
    *,
    catalog_permission: Optional[List[str]] = None,
    order_window_open_minute: Optional[int] = None,
    order_window_close_minute: Optional[int] = None,
    cutoff_minutes_before_close: Optional[int] = None,
    low_amount_bypass_cents: Optional[int] = None,
    status: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if catalog_permission is not None:
        payload["catalog_permission"] = catalog_permission
    if order_window_open_minute is not None:
        payload["order_window_open_minute"] = order_window_open_minute
    if order_window_close_minute is not None:
        payload["order_window_close_minute"] = order_window_close_minute
    if cutoff_minutes_before_close is not None:
        payload["cutoff_minutes_before_close"] = cutoff_minutes_before_close
    if low_amount_bypass_cents is not None:
        payload["low_amount_bypass_cents"] = low_amount_bypass_cents
    if status is not None:
        payload["status"] = status
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Recipe / Ingredient (PRD §3.1)
# ---------------------------------------------------------------------------
def create_recipe_payload(
    *,
    recipe_code: Optional[str] = None,
    name: Optional[str] = None,
    temperature_zone: str = "AMBIENT",
    shelf_life_hours: int = 72,
    production_minutes_per_unit: float = 1.0,
    equipment_class: str = "OVEN",
    unit_price_cents: int = 500,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recipe_code": recipe_code or unique_recipe_code(),
        "name": name or unique_name("Recipe"),
        "temperature_zone": temperature_zone,
        "shelf_life_hours": shelf_life_hours,
        "production_minutes_per_unit": production_minutes_per_unit,
        "equipment_class": equipment_class,
        "unit_price_cents": unit_price_cents,
    }
    payload.update(overrides)
    return payload


def create_ingredient_payload(
    *,
    sku: Optional[str] = None,
    name: Optional[str] = None,
    unit: str = "kg",
    shelf_life_hours: int = 240,
    unit_cost_cents: int = 10,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "sku": sku or unique_ingredient_sku(),
        "name": name or unique_name("Ingredient"),
        "unit": unit,
        "shelf_life_hours": shelf_life_hours,
        "unit_cost_cents": unit_cost_cents,
    }
    payload.update(overrides)
    return payload


def attach_recipe_ingredient_payload(
    *,
    ingredient_id: str,
    quantity_per_unit: float = 1.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "ingredient_id": ingredient_id,
        "quantity_per_unit": quantity_per_unit,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# StoreOrder & OrderLine (PRD §3.2)
# ---------------------------------------------------------------------------
def create_store_order_payload(
    *,
    target_delivery_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_delivery_date": target_delivery_date,
    }
    payload.update(overrides)
    return payload


def append_order_line_payload(
    *,
    recipe_id: str,
    quantity: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recipe_id": recipe_id,
        "quantity": quantity,
    }
    payload.update(overrides)
    return payload


def patch_store_order_payload(
    *,
    target_delivery_date: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if target_delivery_date is not None:
        payload["target_delivery_date"] = target_delivery_date
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ProductionBatch (PRD §3.3)
# ---------------------------------------------------------------------------
def consolidate_payload(
    *,
    target_delivery_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "target_delivery_date": target_delivery_date,
    }
    payload.update(overrides)
    return payload


def schedule_batch_payload(
    *,
    preferred_start_at: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if preferred_start_at is not None:
        payload["preferred_start_at"] = preferred_start_at
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Vehicle / DeliveryRoute (PRD §3.4)
# ---------------------------------------------------------------------------
def create_vehicle_payload(
    *,
    vehicle_code: Optional[str] = None,
    capacity_units: int = 100,
    temperature_zones: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vehicle_code": vehicle_code or unique_vehicle_code(),
        "capacity_units": capacity_units,
        "temperature_zones": temperature_zones or ["AMBIENT"],
    }
    payload.update(overrides)
    return payload


def create_route_payload(
    *,
    vehicle_id: str,
    driver_user_id: str,
    target_delivery_date: str,
    planned_stops: List[Dict[str, Any]],
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "vehicle_id": vehicle_id,
        "driver_user_id": driver_user_id,
        "target_delivery_date": target_delivery_date,
        "planned_stops": planned_stops,
    }
    payload.update(overrides)
    return payload


def planned_stop(
    *,
    store_id: str,
    time_window_start: str,
    time_window_end: str,
    batch_ids: List[str],
) -> Dict[str, Any]:
    return {
        "store_id": store_id,
        "time_window_start": time_window_start,
        "time_window_end": time_window_end,
        "batch_ids": batch_ids,
    }


def reroute_payload(
    *,
    replacement_vehicle_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "replacement_vehicle_id": replacement_vehicle_id,
    }
    payload.update(overrides)
    return payload


def raise_exception_payload(
    *,
    exception_reason: str = "Mechanical issue",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"exception_reason": exception_reason}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Inventory adjust / transfer / dispose (PRD §3.5)
# ---------------------------------------------------------------------------
def adjust_inventory_payload(
    *,
    delta: int,
    reason: str = "manual adjust",
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"delta": delta, "reason": reason}
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


def transfer_inventory_payload(
    *,
    destination_store_id: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"destination_store_id": destination_store_id}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# ReplenishmentRule (PRD §3.5)
# ---------------------------------------------------------------------------
def create_replenishment_rule_payload(
    *,
    recipe_id: str,
    safety_stock_units: int,
    replenish_to_units: int,
    cycle_hours: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recipe_id": recipe_id,
        "safety_stock_units": safety_stock_units,
        "replenish_to_units": replenish_to_units,
        "cycle_hours": cycle_hours,
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# LossRecord (PRD §3.6)
# ---------------------------------------------------------------------------
def create_loss_record_payload(
    *,
    inventory_batch_id: str,
    quantity_lost: int,
    cause: str,
    responsibility_user_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inventory_batch_id": inventory_batch_id,
        "quantity_lost": quantity_lost,
        "cause": cause,
    }
    # Per PRD §3.6: required for DAMAGE/THEFT/PREPARATION; must be omitted/null
    # for SPOILAGE. Tests pass it explicitly when needed.
    if responsibility_user_id is not None:
        payload["responsibility_user_id"] = responsibility_user_id
    payload.update(overrides)
    return payload


def resolve_investigation_payload(
    *,
    resolution_notes: Optional[str] = None,
    version: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if resolution_notes is not None:
        payload["resolution_notes"] = resolution_notes
    if version is not None:
        payload["version"] = version
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Cost allocation (PRD §3.7)
# ---------------------------------------------------------------------------
def run_cost_allocation_payload(
    *,
    period_start: str,
    period_end: str,
    indirect_basis: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "period_start": period_start,
        "period_end": period_end,
        "indirect_basis": indirect_basis,
    }
    payload.update(overrides)
    return payload


__all__ = [
    "unique_store_code",
    "unique_recipe_code",
    "unique_ingredient_sku",
    "unique_vehicle_code",
    "unique_user_id",
    "unique_name",
    "create_store_payload",
    "patch_store_payload",
    "create_recipe_payload",
    "create_ingredient_payload",
    "attach_recipe_ingredient_payload",
    "create_store_order_payload",
    "append_order_line_payload",
    "patch_store_order_payload",
    "consolidate_payload",
    "schedule_batch_payload",
    "create_vehicle_payload",
    "create_route_payload",
    "planned_stop",
    "reroute_payload",
    "raise_exception_payload",
    "adjust_inventory_payload",
    "transfer_inventory_payload",
    "create_replenishment_rule_payload",
    "create_loss_record_payload",
    "resolve_investigation_payload",
    "run_cost_allocation_payload",
]
