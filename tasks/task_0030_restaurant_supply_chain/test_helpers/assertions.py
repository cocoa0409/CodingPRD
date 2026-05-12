"""Per-entity assertions and domain invariant checkers.

Field shape and value-range checks pinned to PRD prose. Each assertion
checks exactly the surface contract the PRD declares; computed-field
presence is asserted only when PRD explicitly states the field is exposed
on the listed endpoint.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable, List, Optional

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
)


# ---------------------------------------------------------------------------
# Common-fields helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def _assert_versioned(data: Dict[str, Any], label: str) -> None:
    """Standard resources expose id, created_at, updated_at, version
    (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be ISO 8601 with 3 fractional digits, "
        f"got {data.get('updated_at')!r}"
    )
    version = data.get("version")
    assert isinstance(version, int) and version >= 1, (
        f"{label}.version must be a positive integer, got {version!r}"
    )


def _assert_immutable(data: Dict[str, Any], label: str) -> None:
    """Immutable / append-only entries expose only id and created_at
    (PRD §2.4: 'RecipeIngredient and AuditLogEntry ... carry only id and
    created_at, and have neither updated_at nor version')."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be ISO 8601, got {data.get('created_at')!r}"
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------
def assert_store(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Store")
    assert isinstance(data["store_code"], str) and len(data["store_code"]) > 0
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["temperature_zone"] in {
        "AMBIENT", "CHILLED", "FROZEN", "MIXED"
    }
    assert isinstance(data["catalog_permission"], list)
    assert isinstance(data["order_window_open_minute"], int)
    assert 0 <= data["order_window_open_minute"] <= 1439
    assert isinstance(data["order_window_close_minute"], int)
    assert 0 <= data["order_window_close_minute"] <= 1439
    assert isinstance(data["cutoff_minutes_before_close"], int)
    assert data["cutoff_minutes_before_close"] >= 0
    assert isinstance(data["low_amount_bypass_cents"], int)
    assert data["low_amount_bypass_cents"] >= 0
    assert data["status"] in {"ACTIVE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# Recipe
# ---------------------------------------------------------------------------
def assert_recipe(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Recipe")
    assert isinstance(data["recipe_code"], str)
    assert isinstance(data["name"], str)
    assert data["temperature_zone"] in {"AMBIENT", "CHILLED", "FROZEN"}
    assert isinstance(data["shelf_life_hours"], int)
    assert data["shelf_life_hours"] > 0
    pmu = data["production_minutes_per_unit"]
    assert isinstance(pmu, (int, float)) and pmu > 0
    assert data["equipment_class"] in {"OVEN", "FRYER", "MIXER", "ASSEMBLY"}
    assert isinstance(data["unit_price_cents"], int)
    assert data["unit_price_cents"] >= 0
    assert data["status"] in {"ACTIVE", "RETIRED"}


# ---------------------------------------------------------------------------
# Ingredient
# ---------------------------------------------------------------------------
def assert_ingredient(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Ingredient")
    assert isinstance(data["sku"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["unit"], str)
    assert isinstance(data["shelf_life_hours"], int)
    assert data["shelf_life_hours"] > 0
    assert isinstance(data["unit_cost_cents"], int)
    assert data["unit_cost_cents"] >= 0


# ---------------------------------------------------------------------------
# RecipeIngredient (immutable per PRD §2.4)
# ---------------------------------------------------------------------------
def assert_recipe_ingredient(data: Dict[str, Any]) -> None:
    _assert_immutable(data, "RecipeIngredient")
    assert is_valid_uuid(data["recipe_id"])
    assert is_valid_uuid(data["ingredient_id"])
    qpu = data["quantity_per_unit"]
    assert isinstance(qpu, (int, float)) and qpu > 0


# ---------------------------------------------------------------------------
# StoreOrder
# ---------------------------------------------------------------------------
def assert_store_order(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "StoreOrder")
    assert is_valid_uuid(data["store_id"])
    assert isinstance(data["target_delivery_date"], str)
    assert data["status"] in {
        "DRAFT", "SUBMITTED", "CONSOLIDATED", "DELIVERED", "CANCELLED"
    }
    assert isinstance(data["total_units"], int) and data["total_units"] >= 0
    assert isinstance(data["total_value_cents"], int)
    assert data["total_value_cents"] >= 0


# ---------------------------------------------------------------------------
# OrderLine (immutable per PRD §2.4 'OrderLine ... appended ... never
# updated, and likewise carries only id and created_at')
# ---------------------------------------------------------------------------
def assert_order_line(data: Dict[str, Any]) -> None:
    _assert_immutable(data, "OrderLine")
    assert is_valid_uuid(data["store_order_id"])
    assert is_valid_uuid(data["recipe_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1


# ---------------------------------------------------------------------------
# ProductionBatch
# ---------------------------------------------------------------------------
def assert_production_batch(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ProductionBatch")
    assert is_valid_uuid(data["recipe_id"])
    assert isinstance(data["planned_units"], int)
    assert data["planned_units"] >= 0
    assert data["status"] in {
        "PLANNED", "SCHEDULED", "IN_PRODUCTION", "COMPLETED", "FAILED"
    }
    assert isinstance(data["target_delivery_date"], str)


# ---------------------------------------------------------------------------
# Vehicle
# ---------------------------------------------------------------------------
def assert_vehicle(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "Vehicle")
    assert isinstance(data["vehicle_code"], str)
    assert isinstance(data["capacity_units"], int)
    assert data["capacity_units"] > 0
    zones = data["temperature_zones"]
    assert isinstance(zones, list) and len(zones) >= 1
    for z in zones:
        assert z in {"AMBIENT", "CHILLED", "FROZEN"}
    assert data["status"] in {"AVAILABLE", "ASSIGNED", "OUT_OF_SERVICE"}


# ---------------------------------------------------------------------------
# DeliveryRoute
# ---------------------------------------------------------------------------
def assert_delivery_route(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "DeliveryRoute")
    assert is_valid_uuid(data["vehicle_id"])
    assert isinstance(data["driver_user_id"], str)
    assert isinstance(data["planned_stops"], list)
    assert isinstance(data["target_delivery_date"], str)
    assert data["status"] in {
        "PLANNED", "DISPATCHED", "IN_TRANSIT",
        "COMPLETED", "EXCEPTION", "REROUTED",
    }


# ---------------------------------------------------------------------------
# InventoryBatch
# ---------------------------------------------------------------------------
def assert_inventory_batch(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "InventoryBatch")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["recipe_id"])
    assert is_valid_uuid(data["production_batch_id"])
    assert isinstance(data["quantity_on_hand"], int)
    assert data["quantity_on_hand"] >= 0
    assert data["alert_tier"] in {"NONE", "TIER1", "TIER2", "TIER3"}
    assert data["status"] in {
        "ON_HAND", "DEPLETED", "DISPOSED", "TRANSFERRED_OUT"
    }


# ---------------------------------------------------------------------------
# ReplenishmentRule
# ---------------------------------------------------------------------------
def assert_replenishment_rule(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "ReplenishmentRule")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["recipe_id"])
    assert isinstance(data["safety_stock_units"], int)
    assert data["safety_stock_units"] >= 0
    assert isinstance(data["replenish_to_units"], int)
    assert data["replenish_to_units"] > data["safety_stock_units"]
    assert isinstance(data["cycle_hours"], int) and data["cycle_hours"] > 0
    assert data["status"] in {"ACTIVE", "SUSPENDED"}


# ---------------------------------------------------------------------------
# LossRecord
# ---------------------------------------------------------------------------
def assert_loss_record(data: Dict[str, Any]) -> None:
    _assert_versioned(data, "LossRecord")
    assert is_valid_uuid(data["store_id"])
    assert is_valid_uuid(data["inventory_batch_id"])
    assert isinstance(data["quantity_lost"], int) and data["quantity_lost"] > 0
    assert data["cause"] in {"SPOILAGE", "DAMAGE", "THEFT", "PREPARATION"}
    assert isinstance(data["financial_impact_cents"], int)
    assert data["financial_impact_cents"] >= 0
    assert isinstance(data["is_abnormal"], bool)
    assert data["investigation_status"] in {"NONE", "PENDING", "RESOLVED"}
    assert data["status"] in {"RECORDED", "APPROVED", "REVERSED"}


# ---------------------------------------------------------------------------
# AuditLogEntry (immutable per PRD §2.6: 'The audit log is append-only
# — entries are never updated, and that is why AuditLogEntry carries no
# version.')
# ---------------------------------------------------------------------------
def assert_audit_log_entry(data: Dict[str, Any]) -> None:
    _assert_immutable(data, "AuditLogEntry")
    assert data["target_type"] in {
        "InventoryBatch", "LossRecord", "StoreOrder",
        "ProductionBatch", "DeliveryRoute"
    }
    assert isinstance(data["target_id"], str)
    assert isinstance(data["action"], str)
    assert isinstance(data["actor_role"], str)
    assert isinstance(data["actor_user_id"], str)


# ---------------------------------------------------------------------------
# Helpers for finding audit entries by predicate
# ---------------------------------------------------------------------------
def find_audit_log_entries(
    entries: Iterable[Dict[str, Any]],
    *,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    action: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for e in entries:
        if target_type is not None and e.get("target_type") != target_type:
            continue
        if target_id is not None and e.get("target_id") != target_id:
            continue
        if action is not None and e.get("action") != action:
            continue
        out.append(e)
    return out


__all__ = [
    "assert_store",
    "assert_recipe",
    "assert_ingredient",
    "assert_recipe_ingredient",
    "assert_store_order",
    "assert_order_line",
    "assert_production_batch",
    "assert_vehicle",
    "assert_delivery_route",
    "assert_inventory_batch",
    "assert_replenishment_rule",
    "assert_loss_record",
    "assert_audit_log_entry",
    "find_audit_log_entries",
]
