"""Domain types for the Traffic Signal Retiming & Corridor Operations API.

Entity TypedDicts, status enums and the role enum, as described in the PRD.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SIGNAL_OPS_ADMIN = "SignalOpsAdmin"
    TIMING_ENGINEER = "TimingEngineer"
    CERTIFYING_ENGINEER = "CertifyingEngineer"
    FIELD_TECHNICIAN = "FieldTechnician"
    CITIZEN_LIAISON = "CitizenLiaison"
    PUBLIC_REQUESTER = "PublicRequester"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class ControllerType(str, Enum):
    TS2_CABINET = "TS2_CABINET"
    ATC_CABINET = "ATC_CABINET"
    LEGACY_170 = "LEGACY_170"


class DetectionStatus(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    NONE = "NONE"


class CommStatus(str, Enum):
    ONLINE = "ONLINE"
    INTERMITTENT = "INTERMITTENT"
    OFFLINE = "OFFLINE"


class WalkingSpeedStandard(str, Enum):
    STD_3_5_FPS = "STD_3_5_FPS"
    EXTENDED_3_0_FPS = "EXTENDED_3_0_FPS"


class OperationalPosture(str, Enum):
    READY = "READY"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class JurisdictionClass(str, Enum):
    ARTERIAL = "ARTERIAL"
    COLLECTOR = "COLLECTOR"
    LOCAL = "LOCAL"


class CorridorSelectionStatus(str, Enum):
    UNSCREENED = "UNSCREENED"
    SCREENED = "SCREENED"
    SELECTED = "SELECTED"
    DEFERRED = "DEFERRED"


class PriorityScoreVariant(str, Enum):
    SCREENING = "SCREENING"
    PROGRAMMING = "PROGRAMMING"


class ContactPref(str, Enum):
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    NONE = "NONE"


class ComplaintCategory(str, Enum):
    COORDINATION = "COORDINATION"
    PEDESTRIAN = "PEDESTRIAN"
    DETECTION = "DETECTION"
    TIMING_OTHER = "TIMING_OTHER"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    LINKED = "LINKED"
    RESOLVED = "RESOLVED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class ProjectStatus(str, Enum):
    DATA_COLLECTION = "DATA_COLLECTION"
    PLAN_DEVELOPMENT = "PLAN_DEVELOPMENT"
    IMPLEMENTED = "IMPLEMENTED"
    FIELD_TUNING = "FIELD_TUNING"
    EVALUATION = "EVALUATION"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class StudyRole(str, Enum):
    BEFORE = "BEFORE"
    AFTER = "AFTER"


class CountPeriod(str, Enum):
    AM_PEAK = "AM_PEAK"
    MID_DAY = "MID_DAY"
    PM_PEAK = "PM_PEAK"


class TodPeriod(str, Enum):
    AM_PEAK = "AM_PEAK"
    MID_DAY = "MID_DAY"
    PM_PEAK = "PM_PEAK"
    OFF_PEAK = "OFF_PEAK"


class RunDirection(str, Enum):
    NB = "NB"
    SB = "SB"
    EB = "EB"
    WB = "WB"


class CoordinationRef(str, Enum):
    MASTER = "MASTER"
    LOCAL_FREE = "LOCAL_FREE"


class TimingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    COORDINATED = "COORDINATED"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    DEPLOYED = "DEPLOYED"
    SUPERSEDED = "SUPERSEDED"


class PedComplianceState(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    WAIVED = "WAIVED"


class PedCheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WAIVED = "WAIVED"


class PedFailureReason(str, Enum):
    PED_CLEAR_SHORT = "PED_CLEAR_SHORT"
    WALK_SHORT = "WALK_SHORT"
    PHASE_TOO_SHORT = "PHASE_TOO_SHORT"


class PriorityType(str, Enum):
    TSP = "TSP"
    EVP = "EVP"


class ApprovalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DeploymentStatus(str, Enum):
    NOT_DEPLOYED = "NOT_DEPLOYED"
    DEPLOYED = "DEPLOYED"
    SUSPENDED = "SUSPENDED"


class FindingCode(str, Enum):
    QUEUE_SPILLBACK = "QUEUE_SPILLBACK"
    EARLY_RETURN_TO_GREEN = "EARLY_RETURN_TO_GREEN"
    PED_CALL_MISSED = "PED_CALL_MISSED"
    DETECTION_FAULT = "DETECTION_FAULT"
    PROGRESSION_BREAK = "PROGRESSION_BREAK"
    NONE = "NONE"


class ObservationResolutionStatus(str, Enum):
    OPEN = "OPEN"
    ADDRESSED = "ADDRESSED"
    DISMISSED = "DISMISSED"


class EvaluationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    INVALIDATED = "INVALIDATED"
    SUPERSEDED = "SUPERSEDED"


class MetricVariant(str, Enum):
    PROVISIONAL_UNWEIGHTED = "PROVISIONAL_UNWEIGHTED"
    CERTIFIED_WEIGHTED = "CERTIFIED_WEIGHTED"


# ---------------------------------------------------------------------------
# Entity shapes.  Resources carrying updated_at + version, and the three
# append-only records that carry only id + created_at (PRD §2.4).
# ---------------------------------------------------------------------------
class Intersection(TypedDict):
    id: str
    location_name: str
    controller_type: str
    detection_status: str
    comm_status: str
    aps_installed: bool
    walking_speed_standard: str
    pedestrian_recall: bool
    max_cycle_length_sec: int
    last_retimed_at: Optional[str]
    timing_plan_age_days: int
    operational_posture: str
    deployed_coordinated_cycle_sec: Optional[int]
    priority_budget_sec: int
    granted_priority_extension_total_sec: int
    unallocated_priority_budget_sec: int
    created_at: str
    updated_at: str
    version: int


class Corridor(TypedDict):
    id: str
    name: str
    jurisdiction_class: str
    annual_volume_change_pct: float
    selection_status: str
    member_count: int
    avg_plan_age_days: float
    complaint_count_12mo: int
    complaint_total_count: int
    complaint_open_count: int
    complaint_linked_count: int
    complaint_terminal_count: int
    priority_score: float
    priority_score_variant: Optional[str]
    screened_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at (no updated_at, no version).
class CorridorMember(TypedDict):
    id: str
    corridor_id: str
    intersection_id: str
    sequence_index: int
    distance_from_prev_ft: float
    created_at: str


class Requester(TypedDict):
    id: str
    display_name: str
    email: str
    contact_pref: str
    open_complaint_count: int
    created_at: str
    updated_at: str
    version: int


class CitizenComplaint(TypedDict):
    id: str
    requester_id: str
    corridor_id: str
    linked_project_id: Optional[str]
    category: str
    narrative: str
    received_at: str
    status: str
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class RetimingProject(TypedDict):
    id: str
    corridor_id: str
    status: str
    study_window_start_at: str
    study_window_days: int
    tuning_round: int
    last_tuning_completed_at: Optional[str]
    lead_engineer_user_id: str
    eligible_member_count: int
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at.
class TurningMovementCount(TypedDict):
    id: str
    project_id: str
    intersection_id: str
    study_role: str
    count_date: str
    period: str
    phase_volumes: dict
    critical_flow_ratio_sum: float
    recommended_cycle_sec: int
    created_at: str


# Append-only: only id + created_at.
class TravelTimeRun(TypedDict):
    id: str
    project_id: str
    study_role: str
    direction: str
    started_at: str
    duration_sec: float
    stops_count: int
    arrivals_on_green_count: int
    total_arrivals: int
    recorded_at: str
    created_at: str


class TimingPlan(TypedDict):
    id: str
    project_id: str
    intersection_id: str
    tod_period: str
    tod_start_min: int
    tod_end_min: int
    coordination_ref: str
    cycle_length_sec: int
    drafted_cycle_length_sec: int
    offset_sec: int
    status: str
    ped_compliance_state: str
    drafted_split_total_sec: int
    effective_split_total_sec: int
    authored_by_user_id: str
    certified_by_user_id: Optional[str]
    return_count: int
    created_at: str
    updated_at: str
    version: int


class PhaseSplit(TypedDict):
    id: str
    timing_plan_id: str
    phase_number: int
    split_sec: int
    effective_split_sec: int
    min_green_sec: int
    yellow_sec: float
    red_clearance_sec: float
    is_pedestrian_phase: bool
    walk_sec: float
    ped_clear_sec: float
    crosswalk_length_ft: float
    created_at: str
    updated_at: str
    version: int


class PedestrianComplianceCheck(TypedDict):
    id: str
    timing_plan_id: str
    phase_number: int
    walking_speed_fps: float
    required_ped_clear_sec: float
    provided_ped_clear_sec: float
    required_walk_sec: float
    provided_walk_sec: float
    required_phase_length_sec: float
    provided_phase_length_sec: float
    result: str
    failure_reason: Optional[str]
    waived_by_user_id: Optional[str]
    waiver_justification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriorityConfig(TypedDict):
    id: str
    intersection_id: str
    priority_type: str
    approval_status: str
    deployment_status: str
    requested_max_extension_sec: int
    max_early_green_sec: int
    conflict_resolution_rank: int
    granted_extension_sec: int
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldObservation(TypedDict):
    id: str
    project_id: str
    intersection_id: str
    tod_period: str
    observed_at: str
    finding_code: str
    requires_adjustment: bool
    resolution_status: str
    observer_user_id: str
    created_at: str
    updated_at: str
    version: int


class PerformanceEvaluation(TypedDict):
    id: str
    project_id: str
    status: str
    metric_variant: str
    mean_travel_time_before_sec: float
    mean_travel_time_after_sec: float
    delay_reduction_pct: float
    total_stops_before: int
    total_stops_after: int
    stops_reduction_pct: float
    aog_pct_before: float
    aog_pct_after: float
    included_after_run_count: int
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
