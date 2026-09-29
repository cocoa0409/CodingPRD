"""Status enumerations and entity shapes for the refueling outage API.

All names are taken from the PRD's own vocabulary.
"""

from typing import Any, Dict, List, Optional, TypedDict


# --- Roles (PRD 2.1) --------------------------------------------------------
class UserRole:
    STATION_ADMIN = "StationAdmin"
    OUTAGE_DIRECTOR = "OutageDirector"
    OUTAGE_PLANNER = "OutagePlanner"
    REACTOR_ENGINEER = "ReactorEngineer"
    CONTRACTOR_COORDINATOR = "ContractorCoordinator"
    ACCESS_AUTHORITY = "AccessAuthority"
    RAD_PROTECTION_PLANNER = "RadProtectionPlanner"
    RAD_PROTECTION_MANAGER = "RadProtectionManager"
    REGULATORY_AFFAIRS = "RegulatoryAffairs"


ALL_ROLES = [
    UserRole.STATION_ADMIN,
    UserRole.OUTAGE_DIRECTOR,
    UserRole.OUTAGE_PLANNER,
    UserRole.REACTOR_ENGINEER,
    UserRole.CONTRACTOR_COORDINATOR,
    UserRole.ACCESS_AUTHORITY,
    UserRole.RAD_PROTECTION_PLANNER,
    UserRole.RAD_PROTECTION_MANAGER,
    UserRole.REGULATORY_AFFAIRS,
]


# --- Shared enumerations ---------------------------------------------------
class StationUnit:
    UNIT_1 = "UNIT_1"
    UNIT_2 = "UNIT_2"


class SafetyFunctionCode:
    DECAY_HEAT_REMOVAL = "DECAY_HEAT_REMOVAL"
    INVENTORY_CONTROL = "INVENTORY_CONTROL"
    ELECTRICAL_POWER = "ELECTRICAL_POWER"
    CONTAINMENT = "CONTAINMENT"
    REACTIVITY_CONTROL = "REACTIVITY_CONTROL"


class OutageStatus:
    PLANNING = "PLANNING"
    SCOPE_LOCKED = "SCOPE_LOCKED"
    EXECUTION = "EXECUTION"
    STARTUP = "STARTUP"
    ONLINE = "ONLINE"
    REVIEWED = "REVIEWED"


class SchedulePosture:
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class AlaraPosture:
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class WorkOrderStatus:
    SCOPED = "SCOPED"
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETE = "COMPLETE"
    DEFERRED = "DEFERRED"


class WorkOrderType:
    MAINTENANCE = "MAINTENANCE"
    MODIFICATION = "MODIFICATION"
    INSPECTION = "INSPECTION"


class WorkOrderOrigin:
    PLANNED_SCOPE = "PLANNED_SCOPE"
    EMERGENT = "EMERGENT"


class Priority:
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    DISCRETIONARY = "DISCRETIONARY"


class ExecutionStatus:
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ConstraintStatus:
    CLEAR = "CLEAR"
    BLOCKED = "BLOCKED"


class CoreLoadPatternStatus:
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ReservationPurpose:
    DISCHARGE = "DISCHARGE"
    FRESH_STAGING = "FRESH_STAGING"
    CONTINGENCY = "CONTINGENCY"


class AvailabilityVariant:
    FULL_CORE_PROTECTED = "FULL_CORE_PROTECTED"
    NOMINAL = "NOMINAL"


class ReservationStatus:
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class WorkerStatus:
    REQUESTED = "REQUESTED"
    SCREENING = "SCREENING"
    BADGE_READY = "BADGE_READY"
    BADGED = "BADGED"
    DENIED = "DENIED"


class BackgroundStatus:
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    ADVERSE = "ADVERSE"


class TrainingStatus:
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"


class Craft:
    PIPEFITTER = "PIPEFITTER"
    ELECTRICIAN = "ELECTRICIAN"
    INSULATOR = "INSULATOR"
    SCAFFOLD_BUILDER = "SCAFFOLD_BUILDER"
    RAD_TECH = "RAD_TECH"
    LABORER = "LABORER"


class RwpStatus:
    DRAFT = "DRAFT"
    HELD_FOR_ALARA = "HELD_FOR_ALARA"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class DoseDirection:
    COMMIT = "COMMIT"
    RELEASE = "RELEASE"


class DoseReason:
    RWP_APPROVED = "RWP_APPROVED"
    RWP_CLOSED_UNDERRUN = "RWP_CLOSED_UNDERRUN"
    RWP_CLOSED_OVERRUN = "RWP_CLOSED_OVERRUN"
    RWP_VOIDED = "RWP_VOIDED"
    WORK_ORDER_DEFERRED = "WORK_ORDER_DEFERRED"


class EmergentItemStatus:
    REPORTED = "REPORTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ABSORBED = "ABSORBED"


class Disposition:
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ABSORBED = "ABSORBED"


class StartupTestStatus:
    PENDING = "PENDING"
    SATISFIED = "SATISFIED"
    FAILED = "FAILED"


class HoldPointType:
    REGULATORY = "REGULATORY"
    STATION = "STATION"
    NONE = "NONE"


class BackgroundOutcome:
    CLEAR = "CLEAR"
    ADVERSE = "ADVERSE"


# --- Entity shapes ---------------------------------------------------------
# Every entity below carries the common system fields of PRD 2.4 --- id,
# created_at, updated_at and version --- except DoseTransaction, which the PRD
# says carries only id and created_at.


class SpentFuelPool(TypedDict, total=False):
    id: str
    station_unit: str
    cells_total: int
    cells_baseline_occupied: int
    full_core_offload_reserve_cells: int
    cells_occupied: int
    cells_reserved: int
    cells_available: int
    protected_cells_available: int
    created_at: str
    updated_at: str
    version: int


class RadArea(TypedDict, total=False):
    id: str
    station_unit: str
    area_code: str
    dose_rate_mrem_per_hr: float
    occupancy_limit_workers: int
    survey_buffer_hours: float
    created_at: str
    updated_at: str
    version: int


class SafetyFunction(TypedDict, total=False):
    id: str
    station_unit: str
    function_code: str
    trains_total: int
    min_trains_required: int
    max_concurrent_oos_trains: int
    created_at: str
    updated_at: str
    version: int


class Outage(TypedDict, total=False):
    id: str
    station_unit: str
    designation: str
    status: str
    schedule_posture: str
    alara_posture: str
    duration_target_hours: float
    dose_budget_total_mrem: float
    cost_budget_usd: float
    scope_freeze_at: str
    required_training_modules: int
    required_badged_workers: int
    dose_committed_mrem: float
    dose_budget_remaining_mrem: float
    approved_scope_cost_usd: float
    scope_contingency_usd: float
    total_scope_cost_usd: float
    approved_emergent_hours: float
    projected_duration_hours: float
    risk_adjusted_duration_hours: float
    badged_worker_count: int
    critical_path_activity_id: Optional[str]
    scope_locked_at: Optional[str]
    actual_duration_hours: Optional[float]
    actual_cost_usd: Optional[float]
    review_notes: Optional[str]
    duration_variance_pct: Optional[float]
    adjusted_duration_variance_pct: Optional[float]
    dose_variance_pct: Optional[float]
    cost_variance_pct: Optional[float]
    outage_performance_index: Optional[float]
    adjusted_performance_index: Optional[float]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    outage_id: str
    wo_type: str
    title: str
    estimated_hours: float
    estimated_cost_usd: float
    estimated_dose_mrem: float
    regulatory_commitment: bool
    safety_function_id: Optional[str]
    requires_rad_work: bool
    status: str
    origin: str
    priority_score: float
    priority: str
    deferral_reason: Optional[str]
    return_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScheduleActivity(TypedDict, total=False):
    id: str
    outage_id: str
    label: str
    planned_start_offset_hours: float
    planned_duration_hours: float
    work_order_id: Optional[str]
    predecessor_activity_id: Optional[str]
    oos_safety_function_id: Optional[str]
    oos_train_label: Optional[str]
    execution_status: str
    constraint_status: str
    path_length_hours: float
    risk_adjusted_path_length_hours: float
    is_critical_path: bool
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoreLoadPattern(TypedDict, total=False):
    id: str
    outage_id: str
    cycle_length_mwd_mtu: float
    fresh_assembly_count: int
    discharge_assembly_count: int
    reactivity_margin_pcm: float
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PoolCellReservation(TypedDict, total=False):
    id: str
    outage_id: str
    spent_fuel_pool_id: str
    cells_requested: int
    purpose: str
    availability_variant: str
    status: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplementalWorker(TypedDict, total=False):
    id: str
    outage_id: str
    full_name: str
    craft: str
    sponsoring_contractor: str
    status: str
    background_status: str
    training_status: str
    training_modules_completed: int
    badge_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RadiologicalWorkPermit(TypedDict, total=False):
    id: str
    outage_id: str
    work_order_id: str
    rad_area_id: str
    worker_count: int
    shielding_factor: float
    planned_start_offset_hours: float
    planned_duration_hours: float
    per_worker_dose_mrem: float
    collective_dose_mrem: float
    contingency_dose_mrem: float
    committed_dose_mrem: float
    alara_review_required: bool
    alara_review_reference: Optional[str]
    actual_dose_mrem: Optional[float]
    void_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DoseTransaction(TypedDict, total=False):
    """PRD 2.4: this entity carries only id and created_at --- no updated_at
    and no version appear in its representation."""

    id: str
    rwp_id: str
    direction: str
    amount_mrem: float
    reason: str
    created_at: str


class EmergentWorkItem(TypedDict, total=False):
    id: str
    discovered_from_work_order_id: str
    description: str
    estimated_hours: float
    estimated_cost_usd: float
    estimated_dose_mrem: float
    discovered_during_inspection: bool
    status: str
    disposition_note: Optional[str]
    created_work_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StartupTest(TypedDict, total=False):
    id: str
    outage_id: str
    test_code: str
    sequence_index: int
    hold_point_type: str
    predicted_reactivity_pcm: float
    measured_reactivity_pcm: Optional[float]
    reactivity_deviation_pcm: Optional[float]
    nrc_release_reference: Optional[str]
    status: str
    created_by_user_id: str
    satisfied_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


JsonDict = Dict[str, Any]
JsonList = List[JsonDict]
