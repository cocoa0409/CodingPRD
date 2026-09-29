"""Domain types for the Semiconductor Fab Yield API.

Entity TypedDicts, status enums and the role enum, all derived from the PRD.

Note on common resource properties (PRD §2.4): every entity except
``MetrologyMeasurement`` carries ``id``, ``created_at``, ``updated_at`` and
``version``.  A metrology reading is an immutable observation, so it carries
only ``id`` and ``created_at``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    PROCESS_ENGINEER = "ProcessEngineer"
    QUALITY_MANAGER = "QualityManager"
    EQUIPMENT_ENGINEER = "EquipmentEngineer"
    FAB_PLANNER = "FabPlanner"
    YIELD_ENGINEER = "YieldEngineer"
    OPERATOR = "Operator"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Shared enumerations
# --------------------------------------------------------------------------


class ProductFamily(str, Enum):
    LOGIC_N5 = "LOGIC_N5"
    LOGIC_N7 = "LOGIC_N7"
    MEMORY_D1 = "MEMORY_D1"


class ToolType(str, Enum):
    LITHO = "LITHO"
    ETCH = "ETCH"
    DEPOSITION = "DEPOSITION"
    IMPLANT = "IMPLANT"
    CMP = "CMP"


# --------------------------------------------------------------------------
# Per-entity status enumerations
# --------------------------------------------------------------------------


class ProcessFlowStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    OBSOLETE = "OBSOLETE"


class RecipeStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    RESTRICTED = "RESTRICTED"


class RecipeRestrictedReason(str, Enum):
    NONE = "NONE"
    ECN_PENDING_IMPLEMENTATION = "ECN_PENDING_IMPLEMENTATION"


class ChangeClass(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ChangeRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    IMPLEMENTED = "IMPLEMENTED"
    REJECTED = "REJECTED"


class EquipmentState(str, Enum):
    IDLE = "IDLE"
    PRODUCTIVE = "PRODUCTIVE"
    PM = "PM"
    DOWN = "DOWN"


class ChamberQualState(str, Enum):
    UNQUALIFIED = "UNQUALIFIED"
    QUALIFIED = "QUALIFIED"
    QUAL_EXPIRED = "QUAL_EXPIRED"
    DISQUALIFIED = "DISQUALIFIED"


class ChamberOccupancyState(str, Enum):
    FREE = "FREE"
    OCCUPIED = "OCCUPIED"


class QualResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class OperatorCertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class OperatorGownState(str, Enum):
    STREET = "STREET"
    GOWNED = "GOWNED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    COMMITTED = "COMMITTED"
    CLOSED = "CLOSED"


class CommitmentTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class LotFlowState(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_PROCESS = "IN_PROCESS"
    AT_SORT = "AT_SORT"
    COMPLETED = "COMPLETED"
    SCRAPPED = "SCRAPPED"


class LotHoldState(str, Enum):
    NONE = "NONE"
    SPC_HOLD = "SPC_HOLD"
    QUAL_HOLD = "QUAL_HOLD"
    ENGINEERING_HOLD = "ENGINEERING_HOLD"


class LotType(str, Enum):
    PRODUCTION = "PRODUCTION"
    ENGINEERING_SPLIT = "ENGINEERING_SPLIT"


class PriorityClass(str, Enum):
    STANDARD = "STANDARD"
    HOT = "HOT"
    SUPER_HOT = "SUPER_HOT"


class StepRunStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class SpcChartStatus(str, Enum):
    MONITORING = "MONITORING"
    SUSPENDED = "SUSPENDED"


class ChartSide(str, Enum):
    NONE = "NONE"
    ABOVE = "ABOVE"
    BELOW = "BELOW"


class MeasurementClassification(str, Enum):
    IN_CONTROL = "IN_CONTROL"
    WARN = "WARN"
    OUT_OF_CONTROL = "OUT_OF_CONTROL"
    OUT_OF_SPEC = "OUT_OF_SPEC"


class ExcursionSourceType(str, Enum):
    SPC = "SPC"
    PARTICLE = "PARTICLE"
    DIE_SORT = "DIE_SORT"


class ExcursionStatus(str, Enum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    DISPOSITIONED = "DISPOSITIONED"


class SeverityVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SeverityBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ContainmentScope(str, Enum):
    NONE = "NONE"
    SPC_CHART = "SPC_CHART"
    CHAMBER = "CHAMBER"
    EQUIPMENT = "EQUIPMENT"


class Disposition(str, Enum):
    NONE = "NONE"
    CONTINUE = "CONTINUE"
    REWORK = "REWORK"
    SCRAP = "SCRAP"


class FailureSignature(str, Enum):
    NONE = "NONE"
    EDGE_RING = "EDGE_RING"
    CENTER_CLUSTER = "CENTER_CLUSTER"
    SCRATCH_LINE = "SCRATCH_LINE"
    PARAMETRIC_SHIFT = "PARAMETRIC_SHIFT"


class DieSortRunStatus(str, Enum):
    SORTED = "SORTED"
    BINNED = "BINNED"


class CycleTimeStatus(str, Enum):
    ON_TARGET = "ON_TARGET"
    AT_RISK = "AT_RISK"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------


class ProcessFlow(TypedDict):
    id: str
    flow_code: str
    product_family: str
    revision: int
    status: str
    step_count: int
    total_standard_hours: float
    released_at: Optional[str]
    superseded_by_flow_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProcessStep(TypedDict):
    id: str
    flow_id: str
    recipe_id: str
    step_seq: int
    step_name: str
    standard_hours: float
    metrology_required: bool
    rework_target_step_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict):
    id: str
    recipe_code: str
    tool_type: str
    target_value: float
    qual_expiry_days: int
    revision: int
    status: str
    restricted_reason: str
    created_at: str
    updated_at: str
    version: int


class RecipeChangeRequest(TypedDict):
    id: str
    recipe_id: str
    change_class: str
    proposed_target: float
    justification: str
    author_user_id: str
    approver_user_id: Optional[str]
    status: str
    revision_round: int
    risk_score: float
    impact_lot_count: int
    requires_full_requal: bool
    pinned_recipe_revision: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict):
    id: str
    equipment_code: str
    tool_type: str
    pm_interval_hours: float
    purge_buffer_hours: float
    hours_since_pm: float
    state: str
    available_capacity_hours: float
    pm_started_at: Optional[str]
    purge_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Chamber(TypedDict):
    id: str
    equipment_id: str
    qualified_recipe_id: str
    chamber_code: str
    particle_limit: float
    particle_count: float
    qual_state: str
    occupancy_state: str
    qualified_at: Optional[str]
    qual_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict):
    id: str
    badge_id: str
    full_name: str
    certified_tool_types: List[str]
    gown_state: str
    gowned_at: Optional[str]
    cert_status: str
    created_at: str
    updated_at: str
    version: int


class WaferStartPlan(TypedDict):
    id: str
    flow_id: str
    product_family: str
    week_start_date: str
    planned_wafer_starts: int
    capacity_budget_hours: float
    cycle_time_target_days: float
    released_wafer_starts: int
    committed_hours: float
    surcharge_hours: float
    commitment_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    plan_id: str
    flow_id: str
    parent_lot_id: Optional[str]
    hold_excursion_id: Optional[str]
    lot_number: str
    wafer_count: int
    origin_wafer_count: int
    priority_class: str
    lot_type: str
    flow_state: str
    hold_state: str
    current_step_seq: int
    rework_count: int
    released_at: Optional[str]
    completed_at: Optional[str]
    actual_cycle_time_days: Optional[float]
    created_at: str
    updated_at: str
    version: int


class StepRun(TypedDict):
    id: str
    lot_id: str
    step_id: str
    operator_id: str
    chamber_id: str
    dispatch_score: float
    reserved_hours: float
    actual_hours: Optional[float]
    status: str
    tracked_in_at: str
    tracked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpcChart(TypedDict):
    id: str
    step_id: str
    param_name: str
    target: float
    sigma: float
    usl: float
    lsl: float
    ucl: float
    lcl: float
    status: str
    consecutive_same_side_count: int
    last_side: str
    violation_count: int
    created_at: str
    updated_at: str
    version: int


class MetrologyMeasurement(TypedDict):
    """Immutable observation (PRD §2.4): only ``id`` and ``created_at``.

    No ``updated_at`` and no ``version``.
    """

    id: str
    step_run_id: str
    spc_chart_id: str
    excursion_id: Optional[str]
    measured_value: float
    classification: str
    run_rule_triggered: bool
    deviation_sigma: float
    created_at: str


class Excursion(TypedDict):
    id: str
    spc_chart_id: Optional[str]
    die_sort_run_id: Optional[str]
    chamber_id: Optional[str]
    lot_id: Optional[str]
    source_type: str
    trigger_value: float
    severity_variant: str
    severity_score: float
    severity_band: str
    affected_lot_count: int
    status: str
    containment_scope: str
    contained_by_user_id: Optional[str]
    dispositioned_by_user_id: Optional[str]
    disposition: str
    failure_signature: str
    created_at: str
    updated_at: str
    version: int


class DieSortRun(TypedDict):
    id: str
    lot_id: str
    gross_die_per_wafer: int
    baseline_yield: float
    premium_target_die: int
    standard_target_die: int
    wafer_results: List[dict]
    sort_yield: float
    yield_loss_ratio: float
    dominant_signature: str
    good_die_total: int
    premium_die: int
    standard_die: int
    value_die: int
    status: str
    created_at: str
    updated_at: str
    version: int
