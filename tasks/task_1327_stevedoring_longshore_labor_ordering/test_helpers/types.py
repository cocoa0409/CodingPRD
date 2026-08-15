"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    STEVEDORE_ADMIN = "StevedoreAdmin"
    STEVEDORE_SUPERINTENDENT = "StevedoreSuperintendent"
    LABOR_HALL_DISPATCHER = "LaborHallDispatcher"
    GANG_FOREMAN = "GangForeman"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PAYROLL_CLERK = "PayrollClerk"
    BILLING_CLERK = "BillingClerk"


# ---------------------------------------------------------------------------
# Enumerations carried on resources
# ---------------------------------------------------------------------------

class VesselCallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BERTHED = "BERTHED"
    WORKING = "WORKING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkPosture(str, Enum):
    NORMAL = "NORMAL"
    PARTIAL_STOPPAGE = "PARTIAL_STOPPAGE"
    FULL_STOPPAGE = "FULL_STOPPAGE"


class ShiftPeriod(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"
    GRAVEYARD = "GRAVEYARD"


class ShiftWindowStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN_FOR_ORDERS = "OPEN_FOR_ORDERS"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class GangType(str, Enum):
    CRANE_GANG = "CRANE_GANG"
    HOLD_GANG = "HOLD_GANG"
    LASHING_GANG = "LASHING_GANG"
    DRIVING_GANG = "DRIVING_GANG"
    GENERAL = "GENERAL"


class Classification(str, Enum):
    CRANE_OPERATOR = "CRANE_OPERATOR"
    HOLDMAN = "HOLDMAN"
    LASHER = "LASHER"
    DRIVER = "DRIVER"
    CLERK = "CLERK"


class GangOrderStatus(str, Enum):
    PLACED = "PLACED"
    DISPATCHING = "DISPATCHING"
    MANNED = "MANNED"
    SHORT_MANNED = "SHORT_MANNED"
    WORKING = "WORKING"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    CHECKED_IN = "CHECKED_IN"
    WORKING = "WORKING"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    BUMPED = "BUMPED"
    CANCELLED = "CANCELLED"


class EquipmentType(str, Enum):
    SHIP_CRANE = "SHIP_CRANE"
    RTG = "RTG"
    FORKLIFT = "FORKLIFT"
    TRACTOR = "TRACTOR"


class EquipmentUnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    DOWN = "DOWN"


class EquipmentAssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    DOWN = "DOWN"


class MoveRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class DamageClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    ACCEPTED = "ACCEPTED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"


class IncidentScope(str, Enum):
    GANG = "GANG"
    VESSEL = "VESSEL"
    TERMINAL = "TERMINAL"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class SafetyIncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    CLEARED = "CLEARED"


class TimesheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class RateVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# Entity shapes. Every resource carries id / created_at / updated_at /
# version (PRD §2.4). total=False because derived fields may be absent or
# null until the computation that produces them runs.
# ---------------------------------------------------------------------------

class VesselCall(TypedDict, total=False):
    id: str
    vessel_name: str
    voyage_number: str
    shipping_line: str
    eta_utc: str
    planned_moves: int
    planned_tons: float
    contracted_mph_target: float
    credit_limit_cents: int
    status: str
    work_posture: str
    actual_moves: int
    actual_tons: float
    created_at: str
    updated_at: str
    version: int


class ShiftWindow(TypedDict, total=False):
    id: str
    vessel_call_id: str
    shift_date: str
    period: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GangOrder(TypedDict, total=False):
    id: str
    shift_window_id: str
    gang_type: str
    required_classification: str
    required_headcount: int
    required_equipment_type: str
    required_equipment_count: int
    filled_headcount: int
    offered_count: int
    status: str
    assigned_equipment_ok: bool
    suspension_count: int
    actual_mph: float
    bonus_eligible: bool
    bonus_pool_cents: int
    bonus_per_worker_cents: int
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    full_name: str
    registration_number: str
    classification: str
    registered_on: str
    base_hourly_rate_cents: int
    status: str
    seniority_rank: int
    created_at: str
    updated_at: str
    version: int


class DispatchAssignment(TypedDict, total=False):
    id: str
    gang_order_id: str
    worker_id: str
    status: str
    seniority_rank_at_dispatch: int
    created_at: str
    updated_at: str
    version: int


class EquipmentUnit(TypedDict, total=False):
    id: str
    unit_code: str
    equipment_type: str
    status: str
    total_breakdowns: int
    created_at: str
    updated_at: str
    version: int


class EquipmentAssignment(TypedDict, total=False):
    id: str
    gang_order_id: str
    equipment_unit_id: str
    window_start_utc: str
    window_end_utc: str
    status: str
    replaced_by_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MoveRecord(TypedDict, total=False):
    id: str
    gang_order_id: str
    recorded_by_worker_id: str
    period_start_utc: str
    period_end_utc: str
    moves_count: int
    tons_lifted: float
    stoppage_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict, total=False):
    id: str
    gang_order_id: str
    reported_by_worker_id: str
    cargo_ref: str
    damage_description: str
    estimated_amount_cents: int
    status: str
    provisional_stevedore_share_cents: int
    fault_pct: Optional[int]
    final_stevedore_liability_cents: Optional[int]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyIncident(TypedDict, total=False):
    id: str
    vessel_call_id: str
    gang_order_id: Optional[str]
    scope: str
    severity: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TimesheetEntry(TypedDict, total=False):
    id: str
    gang_order_id: str
    worker_id: str
    work_minutes: int
    meal_break_taken: bool
    status: str
    rate_cents_snapshot: int
    straight_minutes: int
    ot_minutes: int
    dt_minutes: int
    meal_penalty_minutes: int
    gross_pay_cents: int
    bonus_cents: int
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    vessel_call_id: str
    status: str
    rate_variant: str
    container_line_cents: int
    tonnage_line_cents: int
    manhour_line_cents: int
    equipment_line_cents: int
    stoppage_credit_cents: int
    subtotal_cents: int
    discount_cents: int
    adjustment_total_cents: int
    total_cents: int
    amount_paid_cents: int
    remaining_balance_cents: int
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
