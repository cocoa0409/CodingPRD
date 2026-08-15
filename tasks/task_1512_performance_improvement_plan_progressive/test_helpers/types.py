"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    HR_SYSTEM_ADMIN = "HRSystemAdmin"
    MANAGER = "Manager"
    HR_BUSINESS_PARTNER = "HRBusinessPartner"
    LEGAL_COUNSEL = "LegalCounsel"
    HR_DIRECTOR = "HRDirector"
    EMPLOYEE = "Employee"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_NOTICE = "ON_NOTICE"
    TERMINATED = "TERMINATED"
    RESIGNED = "RESIGNED"


class JobFamily(str, Enum):
    ENGINEERING = "ENGINEERING"
    SALES = "SALES"
    OPERATIONS = "OPERATIONS"
    SUPPORT = "SUPPORT"
    FINANCE = "FINANCE"


class ConcernCategory(str, Enum):
    QUALITY = "QUALITY"
    VELOCITY = "VELOCITY"
    ATTENDANCE = "ATTENDANCE"
    CONDUCT = "CONDUCT"
    COLLABORATION = "COLLABORATION"


class CoachingSeverity(str, Enum):
    INFORMAL = "INFORMAL"
    DOCUMENTED = "DOCUMENTED"
    ESCALATED = "ESCALATED"


class ConcernStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED_INSUFFICIENT = "REJECTED_INSUFFICIENT"
    SUPERSEDED_BY_PIP = "SUPERSEDED_BY_PIP"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class PipStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    CLOSED_SUCCESS = "CLOSED_SUCCESS"
    CLOSED_FAILED = "CLOSED_FAILED"
    CLOSED_TERMINATED = "CLOSED_TERMINATED"
    CLOSED_WITHDRAWN = "CLOSED_WITHDRAWN"


class GoalStatus(str, Enum):
    PENDING = "PENDING"
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    MET = "MET"
    NOT_MET = "NOT_MET"
    WAIVED = "WAIVED"


class CheckInStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class EvidenceSource(str, Enum):
    MANAGER_OBSERVATION = "MANAGER_OBSERVATION"
    SYSTEM_REPORT = "SYSTEM_REPORT"
    PEER_FEEDBACK = "PEER_FEEDBACK"
    SELF_REPORT = "SELF_REPORT"


class Admissibility(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ADMISSIBLE = "ADMISSIBLE"
    INADMISSIBLE = "INADMISSIBLE"


class LegalRecommendation(str, Enum):
    PROCEED = "PROCEED"
    PROCEED_WITH_CAUTION = "PROCEED_WITH_CAUTION"
    HOLD = "HOLD"
    REJECT = "REJECT"


class LegalReviewStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_REVIEW = "IN_REVIEW"
    SUBMITTED = "SUBMITTED"
    OVERRIDDEN = "OVERRIDDEN"


class RiskFactor(str, Enum):
    PROTECTED_CLASS = "PROTECTED_CLASS"
    RECENT_LEAVE = "RECENT_LEAVE"
    WHISTLEBLOWER_HISTORY = "WHISTLEBLOWER_HISTORY"
    PRIOR_COMPLAINT = "PRIOR_COMPLAINT"
    RETALIATION_WINDOW = "RETALIATION_WINDOW"
    DOCUMENTATION_GAP = "DOCUMENTATION_GAP"


class ProposedOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    EXTENSION = "EXTENSION"
    TERMINATION = "TERMINATION"


class OutcomeDecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RebuttalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"


class ConsistencyReviewStatus(str, Enum):
    OPEN = "OPEN"
    ADJUDICATED_CONSISTENT = "ADJUDICATED_CONSISTENT"
    ADJUDICATED_INCONSISTENT = "ADJUDICATED_INCONSISTENT"


class RatingCycleStatus(str, Enum):
    OPEN = "OPEN"
    CALIBRATION = "CALIBRATION"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class HROrgUnit(TypedDict, total=False):
    id: str
    name: str
    current_utc: str
    pip_policy_version: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    hr_org_unit_id: str
    full_name: str
    email: str
    job_family: str
    job_level: int
    manager_id: Optional[str]
    employment_status: str
    active_pip_id: Optional[str]
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatingCycle(TypedDict, total=False):
    id: str
    hr_org_unit_id: str
    label: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: no updated_at, no version.
class ManagerCoachingLogEntry(TypedDict, total=False):
    id: str
    employee_id: str
    author_manager_id: str
    occurred_at: str
    category: str
    severity: str
    narrative: str
    concern_id: Optional[str]
    created_at: str


class PerformanceConcern(TypedDict, total=False):
    id: str
    employee_id: str
    raised_by_manager_id: str
    category: str
    summary: str
    coaching_log_entry_ids: List[str]
    status: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    decided_by_hrbp_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GoalBlueprint(TypedDict, total=False):
    metric_key: str
    target_value: float
    unit: str
    weight: int


class PIPTemplate(TypedDict, total=False):
    id: str
    hr_org_unit_id: str
    name: str
    category: str
    goal_blueprints: List[GoalBlueprint]
    duration_days: int
    check_in_cadence_days: int
    template_status: str
    published_at: Optional[str]
    published_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PerformanceImprovementPlan(TypedDict, total=False):
    id: str
    employee_id: str
    concern_id: str
    template_id: str
    template_published_version: int
    policy_version_at_issuance: int
    issuing_hrbp_id: str
    start_date: str
    end_date: str
    check_in_interval_days: int
    status: str
    provisional_attainment_ratio: float
    final_attainment_ratio: Optional[float]
    extension_count: int
    rebuttal_window_closes_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PIPGoal(TypedDict, total=False):
    id: str
    pip_id: str
    metric_key: str
    target_value: float
    unit: str
    weight: int
    current_value: float
    goal_status: str
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict, total=False):
    id: str
    pip_id: str
    scheduled_for: str
    sequence_index: int
    held_at: Optional[str]
    manager_attended: bool
    hrbp_attended: bool
    status: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: no updated_at, no version.
class EvidenceItem(TypedDict, total=False):
    id: str
    check_in_id: str
    pip_goal_id: str
    observed_value: float
    source: str
    submitted_by_id: str
    submitted_at: str
    admissibility: str
    admissibility_decided_by_id: Optional[str]
    created_at: str


class LegalReview(TypedDict, total=False):
    id: str
    pip_id: str
    requested_by_hrbp_id: str
    assigned_counsel_id: str
    risk_score: Optional[int]
    risk_factors: List[str]
    recommendation: str
    rationale: str
    status: str
    submitted_at: Optional[str]
    decided_by_director_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutcomeDecision(TypedDict, total=False):
    id: str
    pip_id: str
    proposed_by_hrbp_id: str
    proposed_outcome: str
    final_attainment_ratio_at_decision: float
    rationale: str
    status: str
    decided_at: Optional[str]
    decided_by_director_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EmployeeRebuttal(TypedDict, total=False):
    id: str
    pip_id: str
    outcome_decision_id: str
    submitted_by_employee_id: str
    body: str
    status: str
    reviewed_by_hrbp_id: Optional[str]
    resolution: Optional[str]
    resolution_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsistencyReview(TypedDict, total=False):
    id: str
    hr_org_unit_id: str
    target_pip_id: str
    cohort_pip_ids: List[str]
    cohort_size: int
    outcome_disparity_score: Optional[float]
    rating_alignment_score: Optional[float]
    status: str
    opened_by_hrbp_id: str
    adjudicated_by_director_id: Optional[str]
    adjudication_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only: no updated_at, no version.
class RatingCycleOutcomeLink(TypedDict, total=False):
    id: str
    pip_id: str
    rating_cycle_id: str
    employee_id: str
    pip_outcome_at_link: str
    rating_cycle_status_at_link: str
    link_created_at: str
    created_at: str
