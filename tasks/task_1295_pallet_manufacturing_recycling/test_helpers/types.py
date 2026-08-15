"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROCUREMENT_MANAGER = "ProcurementManager"
    YARD_SUPERVISOR = "YardSupervisor"
    HEAT_TREAT_OPERATOR = "HeatTreatOperator"
    SALES_REP = "SalesRep"
    FLEET_PLANNER = "FleetPlanner"
    PLANT_MANAGER = "PlantManager"
    ANY = "Any"


class LumberSpecies(str, Enum):
    PINE = "PINE"
    OAK = "OAK"
    MIXED = "MIXED"


class PalletSpecStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CoreBatchStatus(str, Enum):
    RECEIVING = "RECEIVING"
    SORTING = "SORTING"
    AUDIT = "AUDIT"
    CLOSED = "CLOSED"


class CoreGrade(str, Enum):
    UNSORTED = "UNSORTED"
    A = "A"
    B = "B"
    SCRAP = "SCRAP"


class CoreProcessingStatus(str, Enum):
    YARD = "YARD"
    IN_REPAIR = "IN_REPAIR"
    REPAIRED = "REPAIRED"
    GRINDING_QUEUED = "GRINDING_QUEUED"
    GROUND = "GROUND"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class QualityGrade(str, Enum):
    NEW = "NEW"
    A = "A"
    B = "B"


class HeatTreatStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_HT = "PENDING_HT"
    HT_CERTIFIED = "HT_CERTIFIED"


class HtRunStatus(str, Enum):
    STAGING = "STAGING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    CREDIT_SETTLED = "CREDIT_SETTLED"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PoolReturnStatus(str, Enum):
    LOGGED = "LOGGED"
    GRADED = "GRADED"
    CREDITED = "CREDITED"
    DISPUTED = "DISPUTED"


class RouteStatus(str, Enum):
    PLAN = "PLAN"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class GrindingBatchStatus(str, Enum):
    QUEUED = "QUEUED"
    GRINDING = "GRINDING"
    COMPLETED = "COMPLETED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version.
# The two market-data resources (LumberPriceIndex, SeasonalPriceIndex) are
# immutable once published and carry ONLY id + created_at.

class PalletSpec(TypedDict, total=False):
    id: str
    spec_code: str
    length_in: float
    width_in: float
    height_in: float
    board_count: int
    lumber_species: str
    board_feet_per_pallet: float
    unit_cube_cuft: float
    requires_heat_treatment_default: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LumberPriceIndex(TypedDict, total=False):
    id: str
    species: str
    price_per_mbf_cents: int
    effective_from: str
    effective_to: str
    source_note: str
    created_at: str
    # immutable market-data row: NO updated_at, NO version


class SeasonalPriceIndex(TypedDict, total=False):
    id: str
    season_code: str
    multiplier_bp: int
    effective_from: str
    effective_to: str
    created_at: str
    # immutable market-data band: NO updated_at, NO version


class CorePurchaseBatch(TypedDict, total=False):
    id: str
    supplier_name: str
    agreed_unit_price_cents: int
    manifest_count: int
    estimated_grade_mix: Dict[str, float]
    received_count: int
    provisional_settlement_cents: Optional[int]
    final_settlement_cents: Optional[int]
    grade_yield_variance_bp: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoreUnit(TypedDict, total=False):
    id: str
    batch_id: Optional[str]
    grade: str
    species: str
    condition_notes: str
    repair_cycle_count: int
    processing_status: str
    created_at: str
    updated_at: str
    version: int


class RepairWorkOrder(TypedDict, total=False):
    id: str
    core_unit_id: str
    target_spec_id: str
    target_grade: str
    labor_minutes_estimate: int
    parts_cost_cents: int
    actual_labor_minutes: Optional[int]
    outcome_grade: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    spec_id: str
    origin_type: str
    quantity_total: int
    quantity_available: int
    quality_grade: str
    heat_treat_status: str
    ispm15_mark_id: Optional[str]
    unit_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class HeatTreatmentRun(TypedDict, total=False):
    id: str
    chamber_code: str
    species_profile: str
    capacity_pallets: int
    loaded_pallets: int
    started_at: Optional[str]
    completed_at: Optional[str]
    ispm15_mark_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    company_name: str
    pool_credit_balance_cents: int
    pool_units_outstanding: int
    credit_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_id: str
    order_date: str
    requested_delivery_date: str
    subtotal_cents: Optional[int]
    seasonal_adjustment_cents: Optional[int]
    pool_credit_applied_cents: int
    total_cents: Optional[int]
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    spec_id: str
    quantity: int
    quality_grade_requested: str
    heat_treatment_required: bool
    unit_price_cents: int
    extended_price_cents: Optional[int]
    allocated_lot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PoolReturn(TypedDict, total=False):
    id: str
    customer_id: str
    returned_count: int
    grade_on_return: str
    credit_per_unit_cents: Optional[int]
    total_credit_cents: Optional[int]
    route_stop_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    route_date: str
    trailer_cube_capacity_cuft: float
    cube_used_cuft: float
    planned_miles: float
    provisional_margin_cents: Optional[int]
    final_margin_cents: Optional[int]
    fuel_surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    stop_sequence: int
    order_id: Optional[str]
    stop_type: str
    load_cube_cuft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class GrindingBatch(TypedDict, total=False):
    id: str
    input_core_ids: List[str]
    input_count: int
    output_fiber_cuyd: Optional[float]
    yield_ratio: Optional[float]
    revenue_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
