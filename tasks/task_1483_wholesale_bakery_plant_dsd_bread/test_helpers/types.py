"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    PLANNER = "Planner"
    LINE_OPERATOR = "LineOperator"
    QA_LEAD = "QALead"
    DRIVER = "Driver"
    STORE_RECEIVER = "StoreReceiver"
    THRIFT_CLERK = "ThriftClerk"
    PRICING_ANALYST = "PricingAnalyst"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------

class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class LineCleanliness(str, Enum):
    CLEAN = "CLEAN"
    DIRTY = "DIRTY"
    SANITIZING = "SANITIZING"


class AllergenClass(str, Enum):
    NONE = "NONE"
    SESAME = "SESAME"
    TREE_NUT = "TREE_NUT"
    PEANUT = "PEANUT"


class StaleCreditTier(str, Enum):
    STANDARD = "STANDARD"
    LIMITED = "LIMITED"


class StoreOrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    LOCKED = "LOCKED"
    SHORTED = "SHORTED"
    FULFILLED = "FULFILLED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    CANCELLED = "CANCELLED"


class ProductionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"
    RECONCILED = "RECONCILED"
    SUPERSEDED = "SUPERSEDED"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    MIXING = "MIXING"
    PROOFING = "PROOFING"
    BAKING = "BAKING"
    COOLING = "COOLING"
    OVERPROOFED = "OVERPROOFED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    ABORTED = "ABORTED"


class SanitationCycleStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class RouteStopStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    SKIPPED = "SKIPPED"
    RECONCILED = "RECONCILED"


class StaleReturnStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    CREDITED = "CREDITED"
    REVERSED = "REVERSED"
    REJECTED = "REJECTED"


class ThriftSaleStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class IngredientIndexStatus(str, Enum):
    FORECAST = "FORECAST"
    PUBLISHED = "PUBLISHED"


class SurchargeScheduleStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"


class Ingredient(str, Enum):
    FLOUR = "FLOUR"
    BUTTER = "BUTTER"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 — every resource carries id/created_at/
# updated_at/version; no entity is exempt)
# ---------------------------------------------------------------------------

class Plant(TypedDict, total=False):
    id: str
    name: str
    baseline_flour_index: float
    baseline_butter_index: float
    day_index: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    plant_id: str
    sku: str
    name: str
    allergen_class: str
    unit_weight_g: int
    shelf_life_hours: int
    base_price_cents: int
    flour_share_pct: float
    butter_share_pct: float
    batch_capacity_units: int
    current_surcharge_cents: int
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    plant_id: str
    name: str
    lead_time_hours: int
    min_remaining_life_hours_on_delivery: int
    shelf_capacity_units: int
    stale_credit_tier: str
    status: str
    credit_balance_cents: int
    lifetime_delivered_units: int
    lifetime_stale_units: int
    stale_ratio: float
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    plant_id: str
    name: str
    max_daily_drive_minutes: int
    status: str
    shrink_liability_cents: int
    created_at: str
    updated_at: str
    version: int


class Line(TypedDict, total=False):
    id: str
    plant_id: str
    line_code: str
    hourly_capacity_units: int
    cleanliness: str
    allergen_class_current: str
    created_at: str
    updated_at: str
    version: int


class StoreOrder(TypedDict, total=False):
    id: str
    store_id: str
    plant_id: str
    delivery_date: str
    lines: List[Dict[str, Any]]
    pending_lines: Optional[List[Dict[str, Any]]]
    status: str
    total_units: int
    placed_at: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionPlan(TypedDict, total=False):
    id: str
    plant_id: str
    bake_date: str
    status: str
    planned_units_by_product: Dict[str, int]
    batches_required_by_product: Dict[str, int]
    total_planned_units: int
    flour_required_kg: float
    shortfall_units: int
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict, total=False):
    id: str
    production_plan_id: str
    line_id: str
    product_id: str
    qty_units: int
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    mix_started_at: Optional[str]
    proof_started_at: Optional[str]
    bake_completed_at: Optional[str]
    completed_by_user_id: Optional[str]
    fresh_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SanitationCycle(TypedDict, total=False):
    id: str
    line_id: str
    from_allergen_class: str
    to_allergen_class: str
    required_minutes: int
    status: str
    started_at: Optional[str]
    started_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    plant_id: str
    driver_id: str
    route_date: str
    window_start_at: str
    window_end_at: str
    truck_capacity_units: int
    status: str
    loaded_units: int
    delivered_units: int
    refused_units: int
    returned_stale_units: int
    shrink_units: Optional[int]
    shrink_liability_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    store_order_id: str
    store_id: str
    planned_units: int
    batch_ids: List[str]
    status: str
    delivered_units: Optional[int]
    on_shelf_units_observed: Optional[int]
    stocked_units: Optional[int]
    refused_units: Optional[int]
    shortfall_flag: bool
    created_at: str
    updated_at: str
    version: int


class StaleReturn(TypedDict, total=False):
    id: str
    store_id: str
    route_stop_id: str
    lines: List[Dict[str, Any]]
    verified_lines: Optional[List[Dict[str, Any]]]
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    credited_amount_cents: Optional[int]
    dispute_round: int
    recorded_by_driver_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ThriftSale(TypedDict, total=False):
    id: str
    plant_id: str
    product_id: str
    units: int
    unit_price_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IngredientIndex(TypedDict, total=False):
    id: str
    plant_id: str
    ingredient: str
    period: str
    forecast_value: float
    published_value: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurchargeSchedule(TypedDict, total=False):
    id: str
    product_id: str
    period: str
    provisional_surcharge_cents: int
    final_surcharge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
