"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    HR_ADMIN = "HRAdmin"
    HR_BUSINESS_PARTNER = "HRBusinessPartner"
    TALENT_MANAGER = "TalentManager"
    MANAGER = "Manager"
    EMPLOYEE = "Employee"


# ---------------------------------------------------------------------------
# Field enums
# ---------------------------------------------------------------------------

class DemographicGroup(str, Enum):
    GROUP_A = "GROUP_A"
    GROUP_B = "GROUP_B"
    GROUP_C = "GROUP_C"
    GROUP_D = "GROUP_D"
    UNDISCLOSED = "UNDISCLOSED"


class PerformanceRating(str, Enum):
    LOW = "LOW"
    SOLID = "SOLID"
    STRONG = "STRONG"
    EXCEPTIONAL = "EXCEPTIONAL"


class CriticalityTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class AssessmentMethod(str, Enum):
    WEIGHTED = "WEIGHTED"
    COVERAGE = "COVERAGE"


class ReadinessRating(str, Enum):
    READY_NOW = "READY_NOW"
    READY_1_2 = "READY_1_2"
    READY_3_PLUS = "READY_3_PLUS"


class SuspensionReason(str, Enum):
    PERFORMANCE_CONCERN = "PERFORMANCE_CONCERN"
    EMPLOYEE_REQUEST = "EMPLOYEE_REQUEST"
    ORG_CHANGE = "ORG_CHANGE"


class FillSource(str, Enum):
    SUCCESSION_SLATE = "SUCCESSION_SLATE"
    INTERNAL_POSTING = "INTERNAL_POSTING"


class ClosedReason(str, Enum):
    NO_VIABLE_CANDIDATE = "NO_VIABLE_CANDIDATE"
    ORG_CHANGE = "ORG_CHANGE"


class HoldReason(str, Enum):
    CRITICAL_PROJECT = "CRITICAL_PROJECT"
    PERFORMANCE_PLAN = "PERFORMANCE_PLAN"
    RECENT_MOVE = "RECENT_MOVE"


class RetentionAssessmentMethod(str, Enum):
    POINT_IN_TIME = "POINT_IN_TIME"
    TREND = "TREND"


class TriggerSource(str, Enum):
    MANUAL = "MANUAL"
    BENCH_THIN_AUTO = "BENCH_THIN_AUTO"


class RetentionActionType(str, Enum):
    STAY_INTERVIEW = "STAY_INTERVIEW"
    COMP_REVIEW = "COMP_REVIEW"
    ROLE_REDESIGN = "ROLE_REDESIGN"
    RETENTION_BONUS = "RETENTION_BONUS"


class SnapshotScopeType(str, Enum):
    DEPARTMENT = "DEPARTMENT"
    HIPO_CYCLE = "HIPO_CYCLE"


class ReviewOutcome(str, Enum):
    RETAIN = "RETAIN"
    REMOVE = "REMOVE"


class OfferDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class AssessmentCloseOutcome(str, Enum):
    MITIGATED = "MITIGATED"
    DISMISSED = "DISMISSED"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CriticalRoleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    VACANT = "VACANT"
    RETIRED = "RETIRED"


class BenchPosture(str, Enum):
    EMPTY = "EMPTY"
    THIN = "THIN"
    ADEQUATE = "ADEQUATE"
    STRONG = "STRONG"


class SuccessorStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"
    PROMOTED = "PROMOTED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class VacancyStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    CLOSED_UNFILLED = "CLOSED_UNFILLED"


class PostingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ApplicationStatus(str, Enum):
    PENDING_MANAGER_CONSENT = "PENDING_MANAGER_CONSENT"
    MANAGER_HOLD = "MANAGER_HOLD"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    INTERVIEWING = "INTERVIEWING"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    OFFER_DECLINED = "OFFER_DECLINED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINALIZED = "FINALIZED"


class CalibrationEntryStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CHALLENGED = "CHALLENGED"
    RATIFIED = "RATIFIED"
    APPLIED = "APPLIED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class NominationStatus(str, Enum):
    NOMINATED = "NOMINATED"
    ENDORSED = "ENDORSED"
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMOVED = "REMOVED"
    REJECTED = "REJECTED"
    GRADUATED = "GRADUATED"


class RetentionAssessmentStatus(str, Enum):
    OPEN = "OPEN"
    ACTION_PLANNED = "ACTION_PLANNED"
    ESCALATED = "ESCALATED"
    MITIGATED = "MITIGATED"
    DISMISSED = "DISMISSED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true unless noted)
# ---------------------------------------------------------------------------

class Employee(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    department: str
    job_level: int
    hire_date: str
    demographic_group: str
    performance_rating: str
    rating_history: List[dict]
    current_manager_id: Optional[str]
    employment_status: str
    is_high_potential: bool
    active_hold_count: int
    created_at: str
    updated_at: str
    version: int


class CriticalRole(TypedDict, total=False):
    id: str
    role_title: str
    department: str
    criticality_tier: str
    assessment_method: str
    incumbent_employee_id: Optional[str]
    status: str
    bench_strength: float
    bench_posture: str
    posture_alert: bool
    created_at: str
    updated_at: str
    version: int


class SuccessorEntry(TypedDict, total=False):
    id: str
    critical_role_id: str
    employee_id: str
    readiness_rating: str
    slate_position: int
    readiness_score: float
    status: str
    suspension_reason: Optional[str]
    supersedes_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DevelopmentPlan(TypedDict, total=False):
    id: str
    successor_entry_id: str
    target_readiness: str
    completion_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vacancy(TypedDict, total=False):
    id: str
    critical_role_id: str
    status: str
    fill_deadline: str
    filled_by_employee_id: Optional[str]
    fill_source: Optional[str]
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InternalPosting(TypedDict, total=False):
    id: str
    vacancy_id: str
    title: str
    min_tenure_months: int
    min_job_level: int
    planned_open_date: str
    planned_close_date: str
    status: str
    application_count: int
    created_at: str
    updated_at: str
    version: int


class PostingApplication(TypedDict, total=False):
    id: str
    posting_id: str
    employee_id: str
    submitted_at: str
    consent_deadline: str
    status: str
    hold_reason: Optional[str]
    hold_at: Optional[str]
    hold_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CalibrationSession(TypedDict, total=False):
    id: str
    name: str
    department_scope: str
    scheduled_start: str
    scheduled_end: str
    status: str
    entry_count: int
    ratified_count: int
    created_at: str
    updated_at: str
    version: int


class CalibrationEntry(TypedDict, total=False):
    id: str
    session_id: str
    employee_id: str
    proposed_rating: str
    proposed_by_manager_id: str
    calibrated_rating: Optional[str]
    challenge_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HiPoProgramCycle(TypedDict, total=False):
    id: str
    cycle_name: str
    capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HiPoNomination(TypedDict, total=False):
    id: str
    cycle_id: str
    employee_id: str
    nominated_by_manager_id: str
    endorsed_by_id: Optional[str]
    review_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetentionAssessment(TypedDict, total=False):
    id: str
    employee_id: str
    assessment_method: str
    trigger_source: str
    risk_score: float
    risk_level: str
    action_type: Optional[str]
    action_deadline: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only measurement: id + created_at only,
# NO updated_at, NO version.
class DiversitySnapshot(TypedDict, total=False):
    id: str
    scope_type: str
    scope_ref: str
    total_subjects: int
    underrepresented_count: int
    diversity_index: Optional[float]
    created_at: str
