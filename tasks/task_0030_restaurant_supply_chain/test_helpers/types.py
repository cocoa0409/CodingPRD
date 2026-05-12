"""Domain types for the Restaurant Supply Chain API.

Status enums and entity TypedDicts derived from PRD §2.4 (Resource Identity
and Common Properties) and §3 entity prose.

PRD §2.4 distinguishes two field-shape classes:
- Standard resources (Store, Recipe, Ingredient, StoreOrder, ProductionBatch,
  Vehicle, DeliveryRoute, InventoryBatch, ReplenishmentRule, LossRecord)
  carry id, created_at, updated_at, version.
- Immutable / append-only entries (RecipeIngredient, OrderLine, AuditLogEntry)
  carry only id and created_at — tests MUST NOT assert updated_at or version
  on these.
"""
from __future__ import annotations
from enum import Enum
from typing import TypedDict, Optional, List, Any, Dict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CENTRAL_KITCHEN_PLANNER = "CentralKitchenPlanner"
    STORE_MANAGER = "StoreManager"
    DRIVER = "Driver"
    FINANCE_CONTROLLER = "FinanceController"


# ---------------------------------------------------------------------------
# Temperature / equipment vocabularies (PRD §2.10)
# ---------------------------------------------------------------------------
class TemperatureZone(str, Enum):
    AMBIENT = "AMBIENT"
    CHILLED = "CHILLED"
    FROZEN = "FROZEN"
    MIXED = "MIXED"  # only valid on Store


class EquipmentClass(str, Enum):
    OVEN = "OVEN"
    FRYER = "FRYER"
    MIXER = "MIXER"
    ASSEMBLY = "ASSEMBLY"


# ---------------------------------------------------------------------------
# Entity status enums (PRD §3)
# ---------------------------------------------------------------------------
class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RecipeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StoreOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONSOLIDATED = "CONSOLIDATED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ProductionBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DeliveryRouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    EXCEPTION = "EXCEPTION"
    REROUTED = "REROUTED"


class InventoryBatchStatus(str, Enum):
    ON_HAND = "ON_HAND"
    DEPLETED = "DEPLETED"
    DISPOSED = "DISPOSED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class AlertTier(str, Enum):
    NONE = "NONE"
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class ReplenishmentRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LossCause(str, Enum):
    SPOILAGE = "SPOILAGE"
    DAMAGE = "DAMAGE"
    THEFT = "THEFT"
    PREPARATION = "PREPARATION"


class LossRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    APPROVED = "APPROVED"
    REVERSED = "REVERSED"


class InvestigationStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


class AuditTargetType(str, Enum):
    INVENTORY_BATCH = "InventoryBatch"
    LOSS_RECORD = "LossRecord"
    STORE_ORDER = "StoreOrder"
    PRODUCTION_BATCH = "ProductionBatch"
    DELIVERY_ROUTE = "DeliveryRoute"


class IndirectBasis(str, Enum):
    SALES_VALUE = "SALES_VALUE"
    ORDER_VOLUME = "ORDER_VOLUME"


# ---------------------------------------------------------------------------
# Entity TypedDicts — Standard resources (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Store(TypedDict, total=False):
    id: str
    store_code: str
    name: str
    temperature_zone: str
    catalog_permission: List[str]
    order_window_open_minute: int
    order_window_close_minute: int
    cutoff_minutes_before_close: int
    low_amount_bypass_cents: int
    avg_daily_sales_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict, total=False):
    id: str
    recipe_code: str
    name: str
    temperature_zone: str
    shelf_life_hours: int
    production_minutes_per_unit: float
    equipment_class: str
    unit_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict, total=False):
    id: str
    sku: str
    name: str
    unit: str
    shelf_life_hours: int
    unit_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class StoreOrder(TypedDict, total=False):
    id: str
    store_id: str
    target_delivery_date: str
    submitted_at: Optional[str]
    cancelled_at: Optional[str]
    total_units: int
    total_value_cents: int
    consolidation_batch_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict, total=False):
    id: str
    recipe_id: str
    planned_units: int
    forecast_units: int
    equipment_minutes: float
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    produced_at: Optional[str]
    expires_at: Optional[str]
    target_delivery_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vehicle_code: str
    capacity_units: int
    temperature_zones: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    vehicle_id: str
    driver_user_id: str
    planned_stops: List[Dict[str, Any]]
    total_units_loaded: int
    required_zones: List[str]
    target_delivery_date: str
    dispatched_at: Optional[str]
    completed_at: Optional[str]
    exception_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryBatch(TypedDict, total=False):
    id: str
    store_id: str
    recipe_id: str
    production_batch_id: str
    quantity_on_hand: int
    received_at: str
    expires_at: str
    alert_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplenishmentRule(TypedDict, total=False):
    id: str
    store_id: str
    recipe_id: str
    safety_stock_units: int
    replenish_to_units: int
    cycle_hours: int
    velocity_multiplier: float
    last_evaluated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LossRecord(TypedDict, total=False):
    id: str
    store_id: str
    inventory_batch_id: str
    quantity_lost: int
    cause: str
    responsibility_user_id: Optional[str]
    financial_impact_cents: int
    is_abnormal: bool
    investigation_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entity TypedDicts — Immutable / append-only (id + created_at only)
# ---------------------------------------------------------------------------
class RecipeIngredient(TypedDict, total=False):
    id: str
    recipe_id: str
    ingredient_id: str
    quantity_per_unit: float
    created_at: str


class OrderLine(TypedDict, total=False):
    id: str
    store_order_id: str
    recipe_id: str
    quantity: int
    line_value_cents: int
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    target_type: str
    target_id: str
    action: str
    actor_role: str
    actor_user_id: str
    payload: Dict[str, Any]
    external_systems: List[str]
    created_at: str


__all__ = [
    "UserRole",
    "TemperatureZone",
    "EquipmentClass",
    "StoreStatus",
    "RecipeStatus",
    "StoreOrderStatus",
    "ProductionBatchStatus",
    "VehicleStatus",
    "DeliveryRouteStatus",
    "InventoryBatchStatus",
    "AlertTier",
    "ReplenishmentRuleStatus",
    "LossCause",
    "LossRecordStatus",
    "InvestigationStatus",
    "AuditTargetType",
    "IndirectBasis",
    "Store",
    "Recipe",
    "Ingredient",
    "StoreOrder",
    "ProductionBatch",
    "Vehicle",
    "DeliveryRoute",
    "InventoryBatch",
    "ReplenishmentRule",
    "LossRecord",
    "RecipeIngredient",
    "OrderLine",
    "AuditLogEntry",
]
