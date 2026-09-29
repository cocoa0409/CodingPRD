"""Domain types for the Package Sortation Peak Staffing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them. Every entity in this service carries `id`, `created_at`,
`updated_at` and `version` (PRD §2.4).
"""

from enum import Enum
from typing import Optional, TypedDict


# ─── Role enum (PRD §2.1) ─────────────────────────────

class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    INBOUND_COORDINATOR = "InboundCoordinator"
    SORT_SUPERVISOR = "SortSupervisor"
    LABOR_PLANNER = "LaborPlanner"
    OPS_MANAGER = "OpsManager"
    WORKER = "Worker"


# ─── Status / enum domains ────────────────────────────

class OpsPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class DockDoorKind(str, Enum):
    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"


class DockDoorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SortChuteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONGESTED = "CONGESTED"


class DestinationLaneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ServiceClass(str, Enum):
    GROUND = "GROUND"
    EXPRESS = "EXPRESS"
    FREIGHT = "FREIGHT"


class ChuteAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"
    ENDED = "ENDED"


class TrailerAppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED = "ARRIVED"
    UNLOADING = "UNLOADING"
    JAM_HELD = "JAM_HELD"
    UNLOADED = "UNLOADED"


class PriorityClass(str, Enum):
    CRITICAL = "CRITICAL"
    EXPRESS = "EXPRESS"
    STANDARD = "STANDARD"
    DEFERRED = "DEFERRED"


class ShiftPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    AT_RISK = "AT_RISK"
    CLOSED = "CLOSED"


class WorkerStatus(str, Enum):
    APPLIED = "APPLIED"
    ONBOARDING = "ONBOARDING"
    CLEARED = "CLEARED"
    CERTIFIED = "CERTIFIED"
    SEPARATED = "SEPARATED"


class HireClass(str, Enum):
    CORE = "CORE"
    SEASONAL = "SEASONAL"
    FLEX = "FLEX"


class OnboardingEventType(str, Enum):
    ONBOARDING_STARTED = "ONBOARDING_STARTED"
    BACKGROUND_CLEARED = "BACKGROUND_CLEARED"
    TRAINING_SESSION_COMPLETED = "TRAINING_SESSION_COMPLETED"
    TRAINING_SESSION_MISSED = "TRAINING_SESSION_MISSED"
    REST_DAY_RECORDED = "REST_DAY_RECORDED"
    CERTIFIED = "CERTIFIED"
    SEPARATED = "SEPARATED"


class AttritionRiskBasis(str, Enum):
    COHORT_BASELINE = "COHORT_BASELINE"
    INDIVIDUAL_OBSERVED = "INDIVIDUAL_OBSERVED"


class StaffAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class RoleOnLine(str, Enum):
    UNLOADER = "UNLOADER"
    PRIMARY_SORTER = "PRIMARY_SORTER"
    SECONDARY_SORTER = "SECONDARY_SORTER"
    LOADER = "LOADER"
    JAM_TECH = "JAM_TECH"


class LoadStatus(str, Enum):
    STAGING = "STAGING"
    LOADING = "LOADING"
    LOADED = "LOADED"
    DISPATCHED = "DISPATCHED"


class SealStatus(str, Enum):
    UNSEALED = "UNSEALED"
    SEALED = "SEALED"
    BROKEN = "BROKEN"


class ExceptionType(str, Enum):
    DAMAGED = "DAMAGED"
    UNLABELED = "UNLABELED"
    OVERSIZED = "OVERSIZED"
    MISSORT = "MISSORT"


class PackageExceptionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class Resolution(str, Enum):
    REROUTE = "REROUTE"
    DISPOSE = "DISPOSE"
    RELABEL = "RELABEL"


class InjurySeverity(str, Enum):
    FIRST_AID = "FIRST_AID"
    RECORDABLE = "RECORDABLE"
    SERIOUS = "SERIOUS"


class InjuryReportStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


# ─── Entity shapes ────────────────────────────────────
# Every entity carries id / created_at / updated_at / version (PRD §2.4).

class SortCenter(TypedDict):
    id: str
    code: str
    name: str
    automation_utilization_pct: float
    flex_pool_total: int
    flex_pool_available: int
    flex_pool_reserved: int
    ops_posture: str
    open_jam_count: int
    open_serious_injury_count: int
    packages_inducted_count: int
    wip_package_count: int
    exception_hold_count: int
    disposed_package_count: int
    missort_corrected_count: int
    last_posture_change_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DockDoor(TypedDict):
    id: str
    sort_center_id: str
    door_number: int
    kind: str
    status: str
    turnaround_buffer_min: int
    created_at: str
    updated_at: str
    version: int


class SortChute(TypedDict):
    id: str
    sort_center_id: str
    chute_number: int
    throughput_pph: int
    max_concurrent_destinations: int
    status: str
    jam_hold_count: int
    created_at: str
    updated_at: str
    version: int


class DestinationLane(TypedDict):
    id: str
    sort_center_id: str
    lane_code: str
    region: str
    service_class: str
    forecast_hourly_volume: int
    sorted_package_count: int
    backlog_package_count: int
    assigned_capacity_pph: int
    lane_pressure_ratio: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ChuteAssignment(TypedDict):
    id: str
    chute_id: str
    destination_lane_id: str
    window_start: str
    window_end: str
    status: str
    suspended_reason: Optional[str]
    effective_window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrailerAppointment(TypedDict):
    id: str
    sort_center_id: str
    door_id: str
    trailer_code: str
    window_start: str
    window_end: str
    priority_class: str
    manifest_package_count: int
    unload_sequence_rank: Optional[int]
    jam_count: int
    status: str
    arrived_at: Optional[str]
    unloaded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShiftPlan(TypedDict):
    id: str
    sort_center_id: str
    shift_date: str
    shift_window_start: str
    shift_window_end: str
    shift_hours: float
    forecast_volume: int
    planned_core_headcount: int
    planned_seasonal_headcount: int
    labor_budget_cents: int
    required_headcount: int
    flex_draw_count: int
    planned_labor_cents: int
    committed_headcount: int
    staffing_gap: int
    unfilled_gap: int
    sorted_package_count: int
    missort_package_count: int
    actual_labor_cents: int
    provisional_cost_per_package_cents: Optional[float]
    final_cost_per_package_cents: Optional[float]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    sort_center_id: str
    full_name: str
    hire_class: str
    hire_date: str
    status: str
    training_sessions_completed: int
    training_sessions_missed: int
    no_show_count: int
    completed_assignment_count: int
    consecutive_completed_shifts: int
    tenure_days: int
    attrition_risk_score: float
    attrition_risk_basis: str
    attrition_flagged: bool
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    shift_plan_id: str
    worker_id: str
    line_chute_id: str
    role_on_line: str
    status: str
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    worked_hours: float
    created_at: str
    updated_at: str
    version: int


class OutboundLoad(TypedDict):
    id: str
    sort_center_id: str
    door_id: str
    destination_lane_id: str
    trailer_code: str
    trailer_cube_cuft: float
    cube_used_cuft: float
    cube_utilization_pct: float
    package_count: int
    dispatch_cut_time: str
    load_status: str
    seal_status: str
    seal_code: Optional[str]
    dispatched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackageException(TypedDict):
    id: str
    sort_center_id: str
    exception_type: str
    package_count: int
    from_destination_lane_id: Optional[str]
    to_destination_lane_id: Optional[str]
    outbound_load_id: Optional[str]
    trailer_appointment_id: Optional[str]
    shift_plan_id: Optional[str]
    resolved_via_chute_id: Optional[str]
    status: str
    resolution: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InjuryReport(TypedDict):
    id: str
    sort_center_id: str
    worker_id: str
    chute_id: Optional[str]
    severity: str
    body_part: str
    occurred_at: str
    lost_time_days: int
    status: str
    created_at: str
    updated_at: str
    version: int
