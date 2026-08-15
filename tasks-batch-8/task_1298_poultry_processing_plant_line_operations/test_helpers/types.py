"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    SHIFT_SUPERVISOR = "ShiftSupervisor"
    RECEIVING_CLERK = "ReceivingClerk"
    LINE_OPERATOR = "LineOperator"
    QA_TECHNICIAN = "QATechnician"
    SANITATION_LEAD = "SanitationLead"
    USDA_INSPECTOR = "USDAInspector"
    ORDER_PLANNER = "OrderPlanner"


class LineType(str, Enum):
    EVISCERATION = "EVISCERATION"
    DEBONING = "DEBONING"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class SuspendReason(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    WATER_LIMIT_BREACH = "WATER_LIMIT_BREACH"
    REGULATORY_HOLD = "REGULATORY_HOLD"


class SanitationRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    FAILED_RECHECK = "FAILED_RECHECK"


class PreOpInspectionStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CORRECTING = "CORRECTING"


class WaiverStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class FlockLotStatus(str, Enum):
    BOOKED = "BOOKED"
    RECEIVED = "RECEIVED"
    ON_LINE = "ON_LINE"
    CHILLED = "CHILLED"
    SETTLED = "SETTLED"
    REOPENED = "REOPENED"


class LineRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class CondemnationRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    DISPUTED = "DISPUTED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    ALLOCATED = "ALLOCATED"


class DeboningBatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FinishedLotStatus(str, Enum):
    OPEN = "OPEN"
    TRACE_LOCKED = "TRACE_LOCKED"
    SHIPPED = "SHIPPED"
    RECALLED = "RECALLED"


class RoutingStatus(str, Enum):
    UNROUTED = "UNROUTED"
    FRESH = "FRESH"
    FROZEN = "FROZEN"


# --- common_fields resources: id + created_at + updated_at + version (PRD §2.4) ---

class ProcessingLine(TypedDict, total=False):
    id: str
    line_code: str
    line_type: str
    rated_speed_bpm: int
    created_at: str
    updated_at: str
    version: int


class ProductionShift(TypedDict, total=False):
    id: str
    shift_date: str
    shift_code: str
    shackle_capacity_birds: int
    labor_hours_budget: float
    shacklers_present: int
    eviscerators_present: int
    deboners_present: int
    qa_techs_present: int
    status: str
    suspend_reason: str
    process_water_gallons: float
    chiller_water_gallons: float
    birds_processed: int
    chilled_weight_lb: float
    water_rate_birds_basis: Optional[float]
    water_rate_weight_basis: Optional[float]
    water_breach_active: bool
    chiller_limit_breached: bool
    labor_hours_remaining: float
    started_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SanitationRun(TypedDict, total=False):
    id: str
    shift_id: str
    line_id: str
    window_start: str
    window_end: str
    status: str
    completer_user_id: Optional[str]
    verifier_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreOpInspection(TypedDict, total=False):
    id: str
    shift_id: str
    line_id: str
    status: str
    findings: Optional[str]
    inspector_user_id: Optional[str]
    cycle_count: int
    created_at: str
    updated_at: str
    version: int


class LineSpeedWaiver(TypedDict, total=False):
    id: str
    line_id: str
    max_speed_bpm: int
    effective_from: str
    effective_to: str
    status: str
    denial_count: int
    approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlockLot(TypedDict, total=False):
    id: str
    lot_code: str
    grower_name: str
    booked_head_count: int
    expected_avg_live_weight_lb: float
    receiving_shift_id: str
    status: str
    head_count_received: Optional[int]
    doa_count: Optional[int]
    total_live_weight_lb: Optional[float]
    birds_hung_total: int
    condemned_accounted: int
    carcasses_to_chill: int
    carcass_weight_total_lb: float
    provisional_yield_pct: Optional[float]
    certified_yield_pct: Optional[float]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineRun(TypedDict, total=False):
    id: str
    shift_id: str
    line_id: str
    flock_lot_id: str
    planned_speed_bpm: int
    current_speed_bpm: int
    speed_clamped: bool
    status: str
    birds_hung: Optional[int]
    carcass_weight_lb: Optional[float]
    auto_paused: bool
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CondemnationRecord(TypedDict, total=False):
    id: str
    line_run_id: str
    condemnation_code: str
    carcass_count: int
    amended_carcass_count: Optional[int]
    effective_count: int
    recorded_by_user_id: str
    certified_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductOrder(TypedDict, total=False):
    id: str
    customer_name: str
    product_code: str
    pounds_ordered: float
    temperature_requirement: str
    due_at: str
    fulfillment_status: str
    allocation_status: str
    filled_lb: float
    created_at: str
    updated_at: str
    version: int


class DeboningBatch(TypedDict, total=False):
    id: str
    order_id: str
    flock_lot_id: str
    shift_id: str
    line_id: str
    crew_count: int
    input_weight_lb: float
    estimated_labor_hours: float
    actual_output_weight_lb: Optional[float]
    actual_labor_hours: Optional[float]
    net_weight_lb: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishedLot(TypedDict, total=False):
    id: str
    deboning_batch_id: str
    order_id: str
    trace_code: str
    net_weight_lb: float
    routing_status: str
    status: str
    locked_at: Optional[str]
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- append-only event records: ONLY id + created_at (PRD §2.4) ---

class UtilityMeterReading(TypedDict, total=False):
    id: str
    shift_id: str
    meter_type: str
    gallons: float
    recorded_at: str
    created_at: str


class ChillChainLog(TypedDict, total=False):
    id: str
    finished_lot_id: str
    location: str
    temperature_c: float
    recorded_at: str
    created_at: str
