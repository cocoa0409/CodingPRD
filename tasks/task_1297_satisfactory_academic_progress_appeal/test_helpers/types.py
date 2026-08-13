"""Domain types: entity record shapes, status enums, and the role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class SapStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WARNING = "WARNING"
    SUSPENSION = "SUSPENSION"
    PROBATION = "PROBATION"
    PLAN_PENDING = "PLAN_PENDING"
    PLAN_ACTIVE = "PLAN_ACTIVE"


class TermStatus(str, Enum):
    OPEN = "OPEN"
    GRADING_CLOSED = "GRADING_CLOSED"
    EVALUATED = "EVALUATED"


class EnrollmentStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    POSTED = "POSTED"
    AMENDED = "AMENDED"


class EvaluationStatus(str, Enum):
    OFFICIAL = "OFFICIAL"
    SUPERSEDED = "SUPERSEDED"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class ReasonCategory(str, Enum):
    MEDICAL = "MEDICAL"
    FAMILY_EMERGENCY = "FAMILY_EMERGENCY"
    MILITARY = "MILITARY"
    OTHER = "OTHER"


class Resolution(str, Enum):
    WITH_PLAN = "WITH_PLAN"
    PROBATION_ONLY = "PROBATION_ONLY"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CheckpointOutcome(str, Enum):
    PENDING = "PENDING"
    MET = "MET"
    MISSED = "MISSED"


class NotificationKind(str, Enum):
    STANDING_CHANGE = "STANDING_CHANGE"
    APPEAL_DEADLINE_REMINDER = "APPEAL_DEADLINE_REMINDER"
    APPEAL_DECISION = "APPEAL_DECISION"
    PLAN_RESULT = "PLAN_RESULT"
    REINSTATEMENT = "REINSTATEMENT"


class NotificationStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    STUDENT = "Student"
    REGISTRAR = "Registrar"
    AID_OFFICER = "AidOfficer"
    COMMITTEE_MEMBER = "CommitteeMember"
    AUDITOR = "Auditor"
    AID_ADMINISTRATOR = "AidAdministrator"


class Program(TypedDict, total=False):
    id: str
    code: str
    name: str
    required_credits: int
    min_gpa: float
    min_pace_pct: float
    appeal_window_days: int
    reminder_offset_days: List[int]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    student_number: str
    full_name: str
    program_id: str
    sap_status: str
    cumulative_attempted_credits: int
    cumulative_earned_credits: int
    cumulative_quality_points: float
    cumulative_gpa_hours: int
    cumulative_gpa: Optional[float]
    pace_pct: Optional[float]
    max_tf_exceeded: bool
    created_at: str
    updated_at: str
    version: int


class Term(TypedDict, total=False):
    id: str
    code: str
    seq: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TermEnrollment(TypedDict, total=False):
    id: str
    student_id: str
    term_id: str
    attempted_credits: int
    earned_credits: Optional[int]
    quality_points: Optional[float]
    gpa_hours: Optional[int]
    status: str
    amendment_count: int
    amendment_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SapEvaluation(TypedDict, total=False):
    id: str
    student_id: str
    term_id: str
    status: str
    pace_pct: Optional[float]
    cumulative_gpa: Optional[float]
    max_tf_headroom_credits: int
    max_tf_exceeded: bool
    prior_standing: str
    result_standing: str
    appeal_deadline_at: Optional[str]
    evaluated_at: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    student_id: str
    sap_evaluation_id: str
    reason_category: str
    statement: str
    documents: List[dict]
    status: str
    resolution: Optional[str]
    rationale: Optional[str]
    submitted_at: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AcademicPlan(TypedDict, total=False):
    id: str
    student_id: str
    appeal_id: str
    start_term_id: str
    total_required_credits: int
    coverage_start_seq: int
    coverage_end_seq_exclusive: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanCheckpoint(TypedDict, total=False):
    id: str
    plan_id: str
    term_id: str
    required_term_gpa: float
    required_term_pace_pct: float
    required_earned_credits: int
    actual_term_gpa: Optional[float]
    actual_term_pace_pct: Optional[float]
    actual_earned_credits: Optional[int]
    outcome: str
    created_at: str
    updated_at: str
    version: int


class Notification(TypedDict, total=False):
    id: str
    student_id: str
    kind: str
    detail: str
    scheduled_at: str
    sent_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    # Append-only trail rows: carry only id + created_at, never updated_at/version.
    id: str
    actor_role: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    student_id: Optional[str]
    before_json: Optional[str]
    after_json: Optional[str]
    occurred_at: str
    created_at: str
