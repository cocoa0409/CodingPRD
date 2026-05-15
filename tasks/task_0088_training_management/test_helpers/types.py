"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes mutable resources (CourseCategory, Course,
Instructor, Session, Classroom, OnlineRoom, Enrollment, Trainee,
CreditPool, CertificateTemplate, Certificate — carry
id/created_at/updated_at/version) from append-only / immutable rows
(CourseVersion, InstructorAvailability, CheckIn, ExamAttempt,
EvaluationSurvey, CreditAdjustment, SyncEvent, AuditLog — carry only
id + created_at; no updated_at, no version).
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    TRAINING_ADMIN = "TrainingAdmin"
    COURSE_DESIGNER = "CourseDesigner"
    DEPARTMENT_MANAGER = "DepartmentManager"
    TRAINEE = "Trainee"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CourseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    ON_SHELF = "ON_SHELF"
    OFF_SHELF = "OFF_SHELF"
    ARCHIVED = "ARCHIVED"


class CourseVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class InstructorType(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLACKLISTED = "BLACKLISTED"
    RETIRED = "RETIRED"


class AvailabilityKind(str, Enum):
    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"


class ClassroomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class OnlineRoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SessionMode(str, Enum):
    ONSITE = "ONSITE"
    ONLINE = "ONLINE"
    HYBRID = "HYBRID"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ENROLLMENT_OPEN = "ENROLLMENT_OPEN"
    ENROLLMENT_CLOSED = "ENROLLMENT_CLOSED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentMode(str, Enum):
    SELF = "SELF"
    ASSIGNED = "ASSIGNED"


class EnrollmentStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AttendanceStatus(str, Enum):
    NOT_RECORDED = "NOT_RECORDED"
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    PARTIAL = "PARTIAL"


class TraineeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    OFFBOARDED = "OFFBOARDED"


class CheckInChannel(str, Enum):
    QR = "QR"
    FACE = "FACE"
    IP_RANGE = "IP_RANGE"


class CycleKind(str, Enum):
    ANNUAL = "ANNUAL"
    BIENNIAL = "BIENNIAL"


class CertificateStatus(str, Enum):
    VALID = "VALID"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    RENEWED = "RENEWED"


class SyncSourceSystem(str, Enum):
    HR = "HR"
    IM = "IM"
    LCP = "LCP"


class SyncOutcome(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class AuditSubjectKind(str, Enum):
    ENROLLMENT = "ENROLLMENT"
    CREDIT_POOL = "CREDIT_POOL"


# ---------------------------------------------------------------------------
# Entity TypedDicts — carry id/created_at/updated_at/version  (PRD §2.4)
# ---------------------------------------------------------------------------
class CourseCategory(TypedDict, total=False):
    id: str
    name: str
    parent_id: Optional[str]
    depth: int
    course_count: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict, total=False):
    id: str
    code: str
    title: str
    category_id: str
    objective: str
    outline: str
    duration_hours: float
    prerequisite_course_ids: List[str]
    tags: List[str]
    credit_value: float
    is_charged: bool
    status: str
    current_version_no: int
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    full_name: str
    instructor_type: str
    expertise_tags: List[str]
    qualifications: List[str]
    hourly_rate: float
    travel_cost: float
    avg_evaluation_score: Optional[float]
    status: str
    blacklist_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Classroom(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    status: str
    setup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class OnlineRoom(TypedDict, total=False):
    id: str
    platform: str
    join_url: str
    max_participants: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    course_id: str
    pinned_course_version_id: str
    instructor_id: str
    mode: str
    classroom_id: Optional[str]
    online_room_id: Optional[str]
    start_at: str
    end_at: str
    capacity: int
    waitlist_capacity: int
    enrollment_deadline: str
    status: str
    enrolled_count: int
    waitlist_count: int
    cancellation_fee_charged: bool
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    session_id: str
    trainee_id: str
    mode: str
    status: str
    waitlist_position: Optional[int]
    attendance_status: str
    provisional_credit: float
    final_credit: float
    created_at: str
    updated_at: str
    version: int


class Trainee(TypedDict, total=False):
    id: str
    employee_no: str
    full_name: str
    department: str
    job_level: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditPool(TypedDict, total=False):
    id: str
    trainee_id: str
    cycle_kind: str
    cycle_start: str
    cycle_end: str
    required_credits: float
    accumulated_credits: float
    shortfall_warning_emitted: bool
    created_at: str
    updated_at: str
    version: int


class CertificateTemplate(TypedDict, total=False):
    id: str
    course_id: str
    validity_months: int
    renewal_window_days: int
    requires_attendance: bool
    requires_exam_pass: bool
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    trainee_id: str
    certificate_template_id: str
    source_enrollment_id: str
    issued_at: str
    expires_at: str
    status: str
    verification_code: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / immutable rows — carry only id + created_at  (PRD §2.4)
# ---------------------------------------------------------------------------
class CourseVersion(TypedDict, total=False):
    id: str
    course_id: str
    version_no: int
    snapshot: dict
    status: str
    published_at: Optional[str]
    created_at: str


class InstructorAvailability(TypedDict, total=False):
    id: str
    instructor_id: str
    start_at: str
    end_at: str
    kind: str
    created_at: str


class CheckIn(TypedDict, total=False):
    id: str
    session_id: str
    enrollment_id: str
    channel: str
    source_value: str
    checked_in_at: str
    created_at: str


class ExamAttempt(TypedDict, total=False):
    id: str
    enrollment_id: str
    questions: List[dict]
    total_weight: int
    score: float
    passed: bool
    submitted_at: Optional[str]
    created_at: str


class EvaluationSurvey(TypedDict, total=False):
    id: str
    enrollment_id: str
    content_score: int
    instructor_score: int
    logistics_score: int
    aggregate_score: float
    created_at: str


class CreditAdjustment(TypedDict, total=False):
    id: str
    credit_pool_id: str
    delta: float
    reason: str
    actor_role: str
    created_at: str


class SyncEvent(TypedDict, total=False):
    id: str
    source_system: str
    event_type: str
    payload: dict
    processed_at: Optional[str]
    outcome: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    subject_kind: str
    subject_id: str
    actor_role: str
    actor_id: str
    action: str
    before: dict
    after: dict
    created_at: str


__all__ = [
    # Role enum
    "UserRole",
    # Status enums
    "CourseStatus",
    "CourseVersionStatus",
    "InstructorType",
    "InstructorStatus",
    "AvailabilityKind",
    "ClassroomStatus",
    "OnlineRoomStatus",
    "SessionMode",
    "SessionStatus",
    "EnrollmentMode",
    "EnrollmentStatus",
    "AttendanceStatus",
    "TraineeStatus",
    "CheckInChannel",
    "CycleKind",
    "CertificateStatus",
    "SyncSourceSystem",
    "SyncOutcome",
    "AuditSubjectKind",
    # Mutable entity TypedDicts
    "CourseCategory",
    "Course",
    "Instructor",
    "Classroom",
    "OnlineRoom",
    "Session",
    "Enrollment",
    "Trainee",
    "CreditPool",
    "CertificateTemplate",
    "Certificate",
    # Append-only TypedDicts
    "CourseVersion",
    "InstructorAvailability",
    "CheckIn",
    "ExamAttempt",
    "EvaluationSurvey",
    "CreditAdjustment",
    "SyncEvent",
    "AuditLog",
]
