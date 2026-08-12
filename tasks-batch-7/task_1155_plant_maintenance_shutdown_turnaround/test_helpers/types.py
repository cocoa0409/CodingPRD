"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class TurnaroundStatus(str, Enum):
    PLANNING = "PLANNING"
    SCOPE_FROZEN = "SCOPE_FROZEN"
    MOBILIZATION = "MOBILIZATION"
    EXECUTION = "EXECUTION"
    STARTUP = "STARTUP"
    HANDED_OVER = "HANDED_OVER"
    CANCELLED = "CANCELLED"


class CostPosture(str, Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    AT_RISK = "AT_RISK"
    OVERRUN = "OVERRUN"


class WorkItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    FROZEN = "FROZEN"
    DEFERRED = "DEFERRED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETE = "COMPLETE"
    REOPENED = "REOPENED"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class WorkType(str, Enum):
    CORRECTIVE = "CORRECTIVE"
    PREVENTIVE = "PREVENTIVE"
    INSPECTION = "INSPECTION"
    DISCOVERY_ADDENDUM = "DISCOVERY_ADDENDUM"


class RiskClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class MobilizationStatus(str, Enum):
    INVITED = "INVITED"
    MOBILIZING = "MOBILIZING"
    MOBILIZED = "MOBILIZED"
    DEMOBILIZED = "DEMOBILIZED"


class BadgeStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VETTED = "VETTED"
    BADGED = "BADGED"
    SUSPENDED = "SUSPENDED"
    DEBADGED = "DEBADGED"


class ShiftStatus(str, Enum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ShiftType(str, Enum):
    DAY = "DAY"
    NIGHT = "NIGHT"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PermitType(str, Enum):
    COLD_WORK = "COLD_WORK"
    HOT_WORK = "HOT_WORK"
    CONFINED_SPACE = "CONFINED_SPACE"


class HazardClass(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class IsolationStatus(str, Enum):
    PLANNED = "PLANNED"
    ISOLATED = "ISOLATED"
    VERIFIED = "VERIFIED"
    DEISOLATED = "DEISOLATED"


class IsolationMode(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    SHARED = "SHARED"


class DiscoveryStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"


class LayDownAreaStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    STAGED = "STAGED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    VOIDED = "VOIDED"


class PunchStatus(str, Enum):
    OPEN = "OPEN"
    READY = "READY"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"


class PunchCategory(str, Enum):
    A = "A"
    B = "B"


class UserRole(str, Enum):
    TURNAROUND_MANAGER = "TurnaroundManager"
    PLANNER = "Planner"
    PERMIT_COORDINATOR = "PermitCoordinator"
    CONTRACTOR_SUPERVISOR = "ContractorSupervisor"
    COST_CONTROLLER = "CostController"
    OPERATIONS_REP = "OperationsRep"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Turnaround(TypedDict, total=False):
    id: str
    name: str
    plant_unit: str
    planned_start: str
    planned_end: str
    authorized_budget_cents: int
    contingency_budget_cents: int
    status: str
    cost_posture: str
    committed_cost_cents: int
    reported_cost_cents: int
    critical_path_slip_hours: float
    schedule_run_index: int
    scope_frozen_at: Optional[str]
    handed_over_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkItem(TypedDict, total=False):
    id: str
    turnaround_id: str
    discovery_id: Optional[str]
    planned_shift_id: Optional[str]
    title: str
    system_area: str
    work_type: str
    risk_class: str
    estimated_hours: float
    estimated_cost_cents: int
    requires_permit: bool
    rank_score: Optional[float]
    rank_position: Optional[int]
    is_critical_path: bool
    actual_hours: Optional[float]
    remaining_hours: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkItemDependency(TypedDict, total=False):
    # Append-only edge: carries ONLY id + created_at (no updated_at, no version)
    id: str
    turnaround_id: str
    predecessor_work_item_id: str
    successor_work_item_id: str
    lag_hours: int
    created_at: str


class Contractor(TypedDict, total=False):
    id: str
    turnaround_id: str
    name: str
    craft: str
    headcount_cap: int
    badged_headcount: int
    mobilization_status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    contractor_id: str
    full_name: str
    trade: str
    badge_status: str
    ledger_hours: float
    fatigue_penalty_score: int
    total_shift_hours: float
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    turnaround_id: str
    shift_date: str
    shift_type: str
    starts_at: str
    ends_at: str
    planned_headcount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    shift_id: str
    worker_id: str
    planned_hours: float
    actual_hours: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict, total=False):
    id: str
    work_item_id: str
    permit_type: str
    hazard_class: str
    valid_from: str
    valid_until: str
    required_isolation_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Isolation(TypedDict, total=False):
    id: str
    turnaround_id: str
    equipment_tag: str
    isolation_mode: str
    isolated_from: str
    isolated_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DiscoveryWork(TypedDict, total=False):
    id: str
    turnaround_id: str
    origin_work_item_id: Optional[str]
    description: str
    quoted_cost_cents: int
    quoted_hours: float
    authorized_cost_cents: Optional[int]
    status: str
    reported_by_user_id: str
    authorized_by_user_id: Optional[str]
    appeal_count: int
    triage_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LayDownArea(TypedDict, total=False):
    id: str
    turnaround_id: str
    name: str
    capacity_sqm: int
    occupied_sqm: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StagingReservation(TypedDict, total=False):
    id: str
    laydown_area_id: str
    material_description: str
    area_sqm: int
    window_from: str
    window_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyReportLine(TypedDict, total=False):
    worker_id: str
    shift_id: str
    hours: float
    hazard_flag: bool


class DailyReport(TypedDict, total=False):
    id: str
    turnaround_id: str
    contractor_id: str
    report_date: str
    lines: List[DailyReportLine]
    line_costs_cents: Optional[List[int]]
    labor_cost_cents: Optional[int]
    overhead_cents: Optional[int]
    total_cost_cents: Optional[int]
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PunchItem(TypedDict, total=False):
    id: str
    turnaround_id: str
    work_item_id: str
    category: str
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int
