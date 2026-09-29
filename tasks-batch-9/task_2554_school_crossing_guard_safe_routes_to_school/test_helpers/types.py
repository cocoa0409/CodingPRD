"""Domain types for the Safe Routes to School API: status enums, role enum, entity TypedDicts.

Every field name here is copied verbatim from the PRD resource definitions.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    TRAFFIC_ENGINEER = "TrafficEngineer"
    CROSSING_SUPERVISOR = "CrossingSupervisor"
    CROSSING_GUARD = "CrossingGuard"
    SCHOOL_LIAISON = "SchoolLiaison"
    PUBLIC_REPORTER = "PublicReporter"


class CoveragePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class ControlType(str, Enum):
    UNCONTROLLED = "UNCONTROLLED"
    STOP_SIGN = "STOP_SIGN"
    SIGNALIZED = "SIGNALIZED"


class WarrantStatus(str, Enum):
    NOT_STUDIED = "NOT_STUDIED"
    UNDER_STUDY = "UNDER_STUDY"
    WARRANTED = "WARRANTED"
    CONDITIONAL = "CONDITIONAL"
    NOT_WARRANTED = "NOT_WARRANTED"


class CrashSeverity(str, Enum):
    PROPERTY_DAMAGE_ONLY = "PROPERTY_DAMAGE_ONLY"
    INJURY = "INJURY"
    SEVERE_INJURY = "SEVERE_INJURY"
    FATAL = "FATAL"


class WarrantStudyStatus(str, Enum):
    DRAFT = "DRAFT"
    COUNTING = "COUNTING"
    ANALYZED = "ANALYZED"
    WARRANTED = "WARRANTED"
    CONDITIONAL = "CONDITIONAL"
    NOT_WARRANTED = "NOT_WARRANTED"


class ScoringVariant(str, Enum):
    GAP_ADEQUACY = "GAP_ADEQUACY"
    EXPOSURE_INDEX = "EXPOSURE_INDEX"


class CountPeriod(str, Enum):
    AM_ARRIVAL = "AM_ARRIVAL"
    MIDDAY = "MIDDAY"
    PM_DISMISSAL = "PM_DISMISSAL"


class CertificationStatus(str, Enum):
    APPLICANT = "APPLICANT"
    IN_TRAINING = "IN_TRAINING"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class DutyStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    ON_LEAVE = "ON_LEAVE"


class DutyAction(str, Enum):
    ON_LEAVE = "ON_LEAVE"
    RETURN = "RETURN"


class EquipmentItemType(str, Enum):
    HIGH_VIS_VEST = "HIGH_VIS_VEST"
    STOP_PADDLE = "STOP_PADDLE"
    WHISTLE = "WHISTLE"


class Shift(str, Enum):
    AM = "AM"
    PM = "PM"
    BOTH = "BOTH"


class GuardPostStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CoverageStatus(str, Enum):
    UNSTAFFED = "UNSTAFFED"
    UNCOVERED = "UNCOVERED"
    COVERED = "COVERED"


class PostAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    VACATED = "VACATED"
    SUPERSEDED = "SUPERSEDED"


class CoverageState(str, Enum):
    STAFFED = "STAFFED"
    GAP = "GAP"


class AbsenceReportStatus(str, Enum):
    DISPATCH_PENDING = "DISPATCH_PENDING"
    OFFER_OUT = "OFFER_OUT"
    UNCOVERED_GAP = "UNCOVERED_GAP"
    COVERED = "COVERED"
    RESCINDED = "RESCINDED"


class AbsenceReason(str, Enum):
    ILLNESS = "ILLNESS"
    FAMILY = "FAMILY"
    WEATHER = "WEATHER"
    TRAINING = "TRAINING"
    UNEXCUSED = "UNEXCUSED"


class UrgencyTier(str, Enum):
    SAME_DAY = "SAME_DAY"
    SHORT = "SHORT"
    STANDARD = "STANDARD"


class OfferStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class OfferResponse(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class WalkingRouteStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ADVISORY_HOLD = "ADVISORY_HOLD"
    RETIRED = "RETIRED"


class HazardType(str, Enum):
    NO_SIDEWALK = "NO_SIDEWALK"
    UNCONTROLLED_CROSSING = "UNCONTROLLED_CROSSING"
    HIGH_SPEED_ARTERIAL = "HIGH_SPEED_ARTERIAL"
    RAIL_CROSSING = "RAIL_CROSSING"
    DRIVEWAY_CONFLICT = "DRIVEWAY_CONFLICT"
    POOR_LIGHTING = "POOR_LIGHTING"


class ComplaintStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    REFERRED = "REFERRED"
    RESOLVED = "RESOLVED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class ComplaintType(str, Enum):
    SPEEDING = "SPEEDING"
    NEAR_MISS = "NEAR_MISS"
    FAILURE_TO_YIELD = "FAILURE_TO_YIELD"
    SIGHT_OBSTRUCTION = "SIGHT_OBSTRUCTION"
    SIGNAL_TIMING = "SIGNAL_TIMING"


class SeverityClaim(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Disposition(str, Enum):
    REFER_TO_ENGINEERING = "REFER_TO_ENGINEERING"
    CLOSE_NO_ACTION = "CLOSE_NO_ACTION"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SCORED = "SCORED"
    FUNDED = "FUNDED"
    DEFERRED = "DEFERRED"


class ProjectType(str, Enum):
    RRFB = "RRFB"
    CURB_EXTENSION = "CURB_EXTENSION"
    SIDEWALK_INFILL = "SIDEWALK_INFILL"
    SIGNAL_RETIMING = "SIGNAL_RETIMING"
    RAISED_CROSSWALK = "RAISED_CROSSWALK"


class SuspensionReason(str, Enum):
    WARRANT_LAPSED = "WARRANT_LAPSED"
    RELIABILITY_BREACH = "RELIABILITY_BREACH"


class VacatedReason(str, Enum):
    POST_SUSPENDED = "POST_SUSPENDED"
    GUARD_SUSPENDED = "GUARD_SUSPENDED"


class HoldReason(str, Enum):
    SCHOOL_COVERAGE_SUSPENDED = "SCHOOL_COVERAGE_SUSPENDED"


# --- Ledger fragments (embedded objects, not standalone resources) ---

class ModeShareSurvey(TypedDict, total=False):
    term_code: str
    survey_date: str
    classrooms_reporting: int
    enrollment_at_survey: int
    walk_count: int
    bike_count: int
    bus_count: int
    car_count: int
    other_count: int
    recorded_at: str


class CrashRecord(TypedDict, total=False):
    crash_date: str
    severity: str
    involved_pedestrian: bool
    involved_school_age: bool
    recorded_at: str


class CountSession(TypedDict, total=False):
    session_date: str
    period: str
    observed_minutes: int
    child_count: int
    adult_count: int
    vehicle_count: int
    adequate_gaps: int
    voided: bool
    recorded_at: str


class EquipmentIssuance(TypedDict, total=False):
    item_type: str
    issued_on: str
    recorded_at: str


class DispatchOffer(TypedDict, total=False):
    attempt_number: int
    offered_guard_id: str
    offered_at: str
    offer_expires_at: str
    offer_status: str


class RouteSegment(TypedDict, total=False):
    segment_order: int
    hazard_type: str
    length_ft: int
    mitigated: bool
    intersection_id: Optional[str]


# --- Resources (each carries id, created_at, updated_at and version) ---

class School(TypedDict, total=False):
    id: str
    name: str
    district_code: str
    enrollment_count: int
    session_start_date: str
    session_end_date: str
    am_window_start_utc: str
    am_window_end_utc: str
    pm_window_start_utc: str
    pm_window_end_utc: str
    early_dismissal_pm_offset_minutes: int
    no_school_dates: List[str]
    early_dismissal_dates: List[str]
    baseline_walk_bike_mode_share_pct: float
    mode_share_surveys: List[ModeShareSurvey]
    walk_bike_mode_share_pct: Optional[float]
    walk_bike_mode_share_weighted_pct: Optional[float]
    mode_share_trend_pct: Optional[float]
    latest_survey_term_code: Optional[str]
    active_post_count: int
    covered_post_count: int
    uncovered_post_count: int
    coverage_rate_pct: float
    coverage_posture: str
    created_at: str
    updated_at: str
    version: int


class Intersection(TypedDict, total=False):
    id: str
    school_id: str
    cross_streets: str
    control_type: str
    speed_limit_mph: int
    lanes_crossed: int
    posted_school_zone: bool
    warrant_status: str
    latest_warrant_score: Optional[float]
    crash_history: List[CrashRecord]
    pedestrian_crash_count_window: int
    crash_severity_points: int
    open_complaint_count: int
    created_at: str
    updated_at: str
    version: int


class WarrantStudy(TypedDict, total=False):
    id: str
    intersection_id: str
    count_window_start: str
    count_window_end: str
    authored_by_user_id: str
    finalized_by_user_id: Optional[str]
    status: str
    scoring_variant: Optional[str]
    count_sessions: List[CountSession]
    recount_round: int
    included_child_count: Optional[int]
    included_adequate_gaps: Optional[int]
    included_vehicle_count: Optional[int]
    pedestrian_crash_count_3yr: Optional[int]
    severe_pedestrian_crash_count_3yr: Optional[int]
    warrant_score: Optional[float]
    determination: Optional[str]
    reopen_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Guard(TypedDict, total=False):
    id: str
    full_name: str
    home_zone_code: str
    hire_date: str
    substitute_pool_optin: bool
    certification_status: str
    duty_status: str
    training_hours_completed: float
    hours_since_last_certification: float
    certified_on: Optional[str]
    certification_expires_on: Optional[str]
    equipment_issued: List[EquipmentIssuance]
    equipment_complete: bool
    reliability_score_rolling_90d: float
    reliability_score_season_to_date: float
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GuardPost(TypedDict, total=False):
    id: str
    intersection_id: str
    post_label: str
    zone_code: str
    required_shift: str
    status: str
    suspension_reason: Optional[str]
    coverage_status: str
    open_gap_count: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PostAssignment(TypedDict, total=False):
    id: str
    guard_post_id: str
    guard_id: str
    shift: str
    start_date: str
    end_date: str
    status: str
    vacated_reason: Optional[str]
    open_absence_count: int
    coverage_state: str
    created_at: str
    updated_at: str
    version: int


class AbsenceReport(TypedDict, total=False):
    id: str
    post_assignment_id: str
    guard_id: str
    absence_date: str
    shift: str
    reason: str
    note: Optional[str]
    status: str
    shift_start_utc: str
    notice_hours: float
    urgency_tier: str
    dispatch_attempt_count: int
    dispatch_offers: List[DispatchOffer]
    current_offer_guard_id: Optional[str]
    current_offer_expires_at: Optional[str]
    excluded_guard_ids: List[str]
    substitute_guard_id: Optional[str]
    substitute_cost_cents: Optional[int]
    rescind_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WalkingRoute(TypedDict, total=False):
    id: str
    school_id: str
    route_code: str
    route_name: str
    segments: List[RouteSegment]
    segment_count: int
    hazard_score: float
    status: str
    published_at: Optional[str]
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    intersection_id: str
    complaint_type: str
    reporter_name: str
    reporter_contact: Optional[str]
    occurred_at: str
    narrative: str
    severity_claim: str
    status: str
    disposition: Optional[str]
    triaged_by_user_id: Optional[str]
    triage_note: Optional[str]
    referred_project_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GrantProgram(TypedDict, total=False):
    id: str
    program_name: str
    fiscal_year: int
    total_cents: int
    application_deadline: str
    committed_cents: int
    remaining_cents: int
    funded_project_count: int
    deferred_project_count: int
    next_cycle_carryover_cents: int
    created_at: str
    updated_at: str
    version: int


class InfrastructureProject(TypedDict, total=False):
    id: str
    grant_program_id: str
    intersection_id: str
    source_complaint_id: Optional[str]
    project_type: str
    scope_summary: str
    requested_cost_cents: int
    students_benefited: int
    status: str
    benefit_points: Optional[float]
    cost_factor: Optional[float]
    benefit_cost_score: Optional[float]
    referred_complaint_count_at_scoring: Optional[int]
    awarded_cents: int
    funded_at: Optional[str]
    withdrawal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
