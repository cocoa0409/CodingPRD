"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    REPORTER = "Reporter"
    CASE_MANAGER = "CaseManager"
    BIT_CHAIR = "BITChair"
    COUNSELING_EVALUATOR = "CounselingEvaluator"
    DEAN_OF_STUDENTS = "DeanOfStudents"
    PRIVACY_OFFICER = "PrivacyOfficer"
    SYSTEM_ADMIN = "SystemAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    LEAVE_OF_ABSENCE = "LEAVE_OF_ABSENCE"
    WITHDRAWN = "WITHDRAWN"


class Office(str, Enum):
    FACULTY_AFFAIRS = "FACULTY_AFFAIRS"
    RESIDENCE_LIFE = "RESIDENCE_LIFE"
    COUNSELING_CENTER = "COUNSELING_CENTER"
    DEAN_OF_STUDENTS = "DEAN_OF_STUDENTS"
    BIT_OFFICE = "BIT_OFFICE"
    CAMPUS_SAFETY = "CAMPUS_SAFETY"
    PRIVACY_OFFICE = "PRIVACY_OFFICE"


class ConcernCategory(str, Enum):
    ACADEMIC_DISTRESS = "ACADEMIC_DISTRESS"
    BEHAVIORAL_THREAT = "BEHAVIORAL_THREAT"
    SELF_HARM_RISK = "SELF_HARM_RISK"
    SUBSTANCE_CONCERN = "SUBSTANCE_CONCERN"
    WELLBEING_GENERAL = "WELLBEING_GENERAL"


class ConcernReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class CareCaseStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    PLAN_DRAFTING = "PLAN_DRAFTING"
    PLAN_ACTIVE = "PLAN_ACTIVE"
    MANDATED_ASSESSMENT = "MANDATED_ASSESSMENT"
    LEAVE_DECISION = "LEAVE_DECISION"
    ON_LEAVE = "ON_LEAVE"
    REENTRY_REVIEW = "REENTRY_REVIEW"
    CLOSED = "CLOSED"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    IMMINENT = "IMMINENT"


class ScoringMode(str, Enum):
    INITIAL = "INITIAL"
    REASSESSMENT = "REASSESSMENT"


class InterventionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    SUSPENDED = "SUSPENDED"


class AssessmentOutcome(str, Enum):
    CLEARED = "CLEARED"
    NOT_CLEARED = "NOT_CLEARED"


class MandatedAssessmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class LeaveDecisionValue(str, Enum):
    GRANT_LEAVE = "GRANT_LEAVE"
    DENY_LEAVE = "DENY_LEAVE"


class LeaveDecisionStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class ReentryOutcome(str, Enum):
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    DENIED = "DENIED"


class ReentryStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class CheckinOutcome(str, Enum):
    STABLE = "STABLE"
    ESCALATED = "ESCALATED"


class FollowUpCheckinStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class DisclosureScope(str, Enum):
    SUMMARY_ONLY = "SUMMARY_ONLY"
    FULL_RECORD = "FULL_RECORD"
    SAFETY_MINIMUM = "SAFETY_MINIMUM"


class DisclosureGrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class TrendVariant(str, Enum):
    ENTRY_COHORT = "ENTRY_COHORT"
    ACTIVE_IN_WINDOW = "ACTIVE_IN_WINDOW"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all carry the common fields of PRD §2.4
# (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Student(TypedDict, total=False):
    id: str
    external_ref: str
    full_name: str
    enrollment_status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    office: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class ConcernReport(TypedDict, total=False):
    id: str
    student_id: str
    reporter_id: str
    category: str
    narrative: str
    observed_at: str
    related_report_id: Optional[str]
    care_case_id: Optional[str]
    review_rationale: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CareCase(TypedDict, total=False):
    id: str
    student_id: str
    opened_from_report_id: str
    assigned_case_manager_id: str
    status: str
    current_risk_score: Optional[float]
    current_risk_tier: Optional[str]
    consecutive_stable_checkins: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskScoring(TypedDict, total=False):
    id: str
    case_id: str
    scored_by: str
    mode: str
    harm_to_self: int
    harm_to_others: int
    academic_disruption: int
    substance_involvement: int
    rationale: str
    score: float
    tier: str
    created_at: str
    updated_at: str
    version: int


class InterventionPlan(TypedDict, total=False):
    id: str
    case_id: str
    drafted_by: str
    supersedes_plan_id: Optional[str]
    objectives: List[str]
    success_criteria: str
    reentry_conditions: List[str]
    revision_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MandatedAssessment(TypedDict, total=False):
    id: str
    case_id: str
    ordered_by: str
    evaluator_id: str
    due_at: str
    rationale: str
    outcome: Optional[str]
    findings_summary: Optional[str]
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaveDecision(TypedDict, total=False):
    id: str
    case_id: str
    requested_by: str
    decided_by: Optional[str]
    decision: Optional[str]
    rationale: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReentryEvaluation(TypedDict, total=False):
    id: str
    case_id: str
    leave_decision_id: str
    petitioned_by: str
    petition_summary: str
    decided_by: Optional[str]
    outcome: Optional[str]
    conditions: Optional[List[str]]
    rationale: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FollowUpCheckin(TypedDict, total=False):
    id: str
    case_id: str
    due_at: str
    completed_at: Optional[str]
    outcome: Optional[str]
    note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisclosureGrant(TypedDict, total=False):
    id: str
    case_id: str
    requested_by: Optional[str]
    approved_by: Optional[str]
    to_office: str
    scope: str
    effective_from: str
    expires_at: str
    purpose: str
    auto_approved: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TrendReport(TypedDict, total=False):
    id: str
    term_code: str
    window_start: str
    window_end: str
    variant: str
    total_cases: int
    closed_in_window: int
    closure_rate_pct: float
    avg_days_to_close: float
    category_distribution: Dict[str, float]
    created_at: str
    updated_at: str
    version: int
