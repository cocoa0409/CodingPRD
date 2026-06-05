"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resource shapes described in the PRD. Full top-level resources carry
id, created_at, updated_at, and version; the two append-only audit records
(QuizAttempt, EscalationEvent) carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum -------------------------------------------------------------
class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    MANAGER = "Manager"
    LEARNER = "Learner"


# --- Status enums ----------------------------------------------------------
class CourseStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class LearningPathStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class EnrollmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"
    WAIVED = "WAIVED"


class PathEnrollmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class TrackingSessionStatus(str, Enum):
    INITIALIZED = "INITIALIZED"
    RUNNING = "RUNNING"
    TERMINATED = "TERMINATED"


# --- Enumerated input value sets ------------------------------------------
class Department(str, Enum):
    ENGINEERING = "ENGINEERING"
    SALES = "SALES"
    FINANCE = "FINANCE"
    HR = "HR"
    OPERATIONS = "OPERATIONS"


class JobRole(str, Enum):
    IC = "IC"
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"


class ContentType(str, Enum):
    SCORM = "SCORM"
    XAPI = "XAPI"


class GradingPolicy(str, Enum):
    HIGHEST_SCORE = "HIGHEST_SCORE"
    LATEST_ATTEMPT = "LATEST_ATTEMPT"


class CeuPolicy(str, Enum):
    STANDARD = "STANDARD"
    SCORE_WEIGHTED = "SCORE_WEIGHTED"


class LessonStatus(str, Enum):
    INCOMPLETE = "INCOMPLETE"
    COMPLETED = "COMPLETED"
    PASSED = "PASSED"
    FAILED = "FAILED"


# --- Entity TypedDicts -----------------------------------------------------
# common_fields: true → id + created_at + updated_at + version
class Employee(TypedDict):
    id: str
    email: str
    full_name: str
    department: str
    job_role: str
    manager_id: Optional[str]
    total_ceu_earned: float
    compliant_required_count: int
    compliance_score: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    code: str
    title: str
    content_type: str
    passing_score: int
    max_attempts: int
    ceu_credits: float
    grading_policy: str
    ceu_policy: str
    is_recurring: bool
    recurrence_months: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CoursePrerequisite(TypedDict):
    id: str
    course_id: str
    prerequisite_course_id: str
    created_at: str
    updated_at: str
    version: int


class LearningPath(TypedDict):
    id: str
    code: str
    title: str
    enforce_sequence: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PathStep(TypedDict):
    id: str
    learning_path_id: str
    course_id: str
    sequence_index: int
    is_mandatory: bool
    weight: int
    created_at: str
    updated_at: str
    version: int


class AssignmentRule(TypedDict):
    id: str
    target_department: str
    target_job_role: str
    course_id: Optional[str]
    learning_path_id: Optional[str]
    due_in_days: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    employee_id: str
    course_id: str
    path_enrollment_id: Optional[str]
    assignment_rule_id: Optional[str]
    is_required: bool
    due_date: str
    best_score: Optional[int]
    latest_score: Optional[int]
    final_grade: Optional[int]
    attempts_used: int
    cycle_index: int
    escalation_tier: int
    certificate_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PathEnrollment(TypedDict):
    id: str
    employee_id: str
    learning_path_id: str
    assignment_rule_id: Optional[str]
    due_date: str
    progress_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    employee_id: str
    course_id: str
    enrollment_id: str
    ceu_credited: float
    issued_at: str
    expires_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrackingSession(TypedDict):
    id: str
    enrollment_id: str
    content_type: str
    started_at: str
    terminated_at: Optional[str]
    lesson_status: Optional[str]
    progress_pct: int
    reported_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClockState(TypedDict):
    id: str
    current_utc: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false → append-only: ONLY id + created_at (no updated_at, no version)
class QuizAttempt(TypedDict):
    id: str
    enrollment_id: str
    cycle_index: int
    attempt_number: int
    score: int
    passed: bool
    created_at: str


class EscalationEvent(TypedDict):
    id: str
    enrollment_id: str
    employee_id: str
    manager_id: Optional[str]
    tier: int
    days_overdue: int
    acknowledged: bool
    created_at: str
