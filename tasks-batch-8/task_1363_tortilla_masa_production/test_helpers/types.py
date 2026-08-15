"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    MILLER_OPERATOR = "MillerOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    LINE_SCHEDULER = "LineScheduler"
    SANITATION_TECH = "SanitationTech"
    PACKAGING_LEAD = "PackagingLead"
    ROUTE_DISPATCHER = "RouteDispatcher"


class CornVariety(str, Enum):
    WHITE_CORN = "WHITE_CORN"
    YELLOW_CORN = "YELLOW_CORN"
    BLUE_CORN = "BLUE_CORN"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    CONDITIONED = "CONDITIONED"
    DEPLETED = "DEPLETED"
    REJECTED = "REJECTED"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    COOKING = "COOKING"
    STEEPING = "STEEPING"
    MILLING = "MILLING"
    MASA_AVAILABLE = "MASA_AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"
    REJECTED = "REJECTED"


class DiameterIn(str, Enum):
    D6 = "D6"
    D8 = "D8"
    D10 = "D10"
    D12 = "D12"


class ProductChannel(str, Enum):
    RETAIL = "RETAIL"
    FOODSERVICE = "FOODSERVICE"


class PreservativeSystem(str, Enum):
    NONE = "NONE"
    PROPIONATE = "PROPIONATE"
    FUMARIC_ACID = "FUMARIC_ACID"


class AllergenClass(str, Enum):
    CORN_ONLY = "CORN_ONLY"
    WHEAT_FLOUR = "WHEAT_FLOUR"
    SOY_BLENDED = "SOY_BLENDED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class AllergenZone(str, Enum):
    DEDICATED_CORN = "DEDICATED_CORN"
    SHARED = "SHARED"


class LineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"


class LinePosture(str, Enum):
    AVAILABLE = "AVAILABLE"
    RUNNING = "RUNNING"
    CHANGEOVER_PENDING = "CHANGEOVER_PENDING"


class ProductionStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QcStatus(str, Enum):
    PENDING = "PENDING"
    ON_HOLD = "ON_HOLD"
    PASSED = "PASSED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class ChangeoverLevel(str, Enum):
    FLUSH = "FLUSH"
    WET_WASH = "WET_WASH"
    FULL_SANITATION = "FULL_SANITATION"


class ChangeoverStatus(str, Enum):
    REQUIRED = "REQUIRED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class VerificationMethod(str, Enum):
    AVERAGE_WEIGHT = "AVERAGE_WEIGHT"
    COUNT_VERIFY = "COUNT_VERIFY"


class PackStatus(str, Enum):
    OPEN = "OPEN"
    PACKING = "PACKING"
    PASSED = "PASSED"
    HOLD = "HOLD"
    SEALED = "SEALED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CustomerChannel(str, Enum):
    RETAIL_GROCERY = "RETAIL_GROCERY"
    TORTILLERIA = "TORTILLERIA"
    FOODSERVICE_DIST = "FOODSERVICE_DIST"


class PriorityTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class CreditStanding(str, Enum):
    GOOD = "GOOD"
    HOLD = "HOLD"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AllotmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    DELIVERED = "DELIVERED"
    SHORTED = "SHORTED"


# PRD §2.4: every entity carries id, created_at, updated_at, version.


class IngredientLot(TypedDict, total=False):
    id: str
    lot_code: str
    corn_variety: str
    received_kg: float
    moisture_pct: float
    drawn_kg: float
    available_kg: float
    lot_status: str
    created_at: str
    updated_at: str
    version: int


class NixtamalBatch(TypedDict, total=False):
    id: str
    ingredient_lot_id: str
    corn_kg: float
    lime_pct: float
    cook_minutes: int
    steep_target_hours: int
    cook_started_at: Optional[str]
    steep_started_at: Optional[str]
    recook_count: int
    theoretical_masa_kg: float
    actual_masa_kg: Optional[float]
    masa_wasted_kg: Optional[float]
    masa_available_kg: float
    yield_variance_pct: Optional[float]
    batch_status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku_code: str
    diameter_in: str
    count_per_pack: int
    packs_per_case: int
    unit_weight_g: float
    channel: str
    preservative_system: str
    shelf_life_days: int
    allergen_class: str
    weight_tolerance_pct: float
    declared_pack_net_g: float
    declared_case_net_g: float
    product_status: str
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    line_code: str
    allergen_zone: str
    cases_per_hour: int
    current_product_id: Optional[str]
    line_posture: str
    line_status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    product_id: str
    line_id: str
    planned_cases: int
    start_at: str
    end_at: str
    masa_required_kg: float
    masa_reserved_kg: float
    produced_cases: int
    production_status: str
    qc_status: str
    created_at: str
    updated_at: str
    version: int


class BatchAllocation(TypedDict, total=False):
    id: str
    nixtamal_batch_id: str
    production_run_id: str
    allocated_kg: float
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


class ChangeoverRecord(TypedDict, total=False):
    id: str
    line_id: str
    from_product_id: str
    to_product_id: str
    production_run_id: Optional[str]
    required_level: str
    required_downtime_min: int
    performed_by: Optional[str]
    fail_count: int
    changeover_status: str
    created_at: str
    updated_at: str
    version: int


class PackOrder(TypedDict, total=False):
    id: str
    production_run_id: str
    cases_planned: int
    verification_method: str
    cases_packed: Optional[int]
    avg_pack_weight_g: Optional[float]
    count_accuracy_pct: Optional[float]
    cases_available: int
    sealed_at: Optional[str]
    expires_on: Optional[str]
    pack_status: str
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict, total=False):
    id: str
    account_name: str
    channel: str
    region: str
    base_weekly_cases: int
    priority_tier: str
    min_shelf_life_pct: int
    credit_standing: str
    created_at: str
    updated_at: str
    version: int


class SeasonalWindow(TypedDict, total=False):
    id: str
    window_name: str
    starts_on: str
    ends_on: str
    demand_multiplier: float
    forecast_total_cases: int
    is_strict: bool
    window_status: str
    created_at: str
    updated_at: str
    version: int


class SeasonalAllotment(TypedDict, total=False):
    id: str
    seasonal_window_id: str
    customer_id: str
    allotted_cases: int
    consumed_cases: int
    remaining_cases: int
    allotment_status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    route_code: str
    route_date: str
    region: str
    vehicle_capacity_cases: int
    committed_cases: int
    open_cases: int
    route_status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    customer_id: str
    pack_order_id: str
    requested_cases: int
    allocated_cases: int
    delivered_cases: Optional[int]
    shortage_cases: int
    stop_status: str
    created_at: str
    updated_at: str
    version: int
