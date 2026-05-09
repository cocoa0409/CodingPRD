"""Domain types for the Edu Live Stream API.

Entity TypedDicts, status enums, and the role enum are derived from PRD §2.1
(roles), §2.4 (common resource properties), and §3 (entity lifecycles).

Note on common-fields branching (PRD §2.4): a handful of entities are append-only
or immutable snapshots and therefore carry only `id` and `created_at`; both
`updated_at` and `version` are absent for them. Those entities are
SyllabusRevision, Announcement, Attendance, WatchSession, AuditLogEntry, and
Clock. Their TypedDicts must omit the missing fields so test assertions never
demand fields that the implementer is correctly told not to return.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ──────────────────────────────────────────────────────────
# Roles (PRD §2.1)
# ──────────────────────────────────────────────────────────

class UserRole(str, Enum):
    INSTRUCTOR = "Instructor"
    TEACHING_ASSISTANT = "TeachingAssistant"
    STUDENT = "Student"
    ACADEMIC_ADMIN = "AcademicAdmin"


# ──────────────────────────────────────────────────────────
# Status enums (PRD §3)
# ──────────────────────────────────────────────────────────

class CourseStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"
    REJECTED = "REJECTED"
    DELISTED = "DELISTED"


class CoursePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class EnrollmentPaymentStatus(str, Enum):
    PAID = "PAID"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"


class EnrollmentLearningStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_RISK = "AT_RISK"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class LiveClassStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"
    RESCHEDULED = "RESCHEDULED"


class AttendanceMark(str, Enum):
    ATTENDED = "ATTENDED"
    LATE = "LATE"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"


class CheckinMethod(str, Enum):
    TIME_WINDOW = "TIME_WINDOW"
    CODE = "CODE"
    FACE = "FACE"
    LEAVE = "LEAVE"


class LeaveRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AssignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class AssignmentFormat(str, Enum):
    TEXT = "TEXT"
    FILE = "FILE"
    CODE = "CODE"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    GRADED = "GRADED"


class RefundRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AnnouncementAuthorRole(str, Enum):
    INSTRUCTOR = "INSTRUCTOR"
    TEACHING_ASSISTANT = "TEACHING_ASSISTANT"


class AuditActorRole(str, Enum):
    INSTRUCTOR = "INSTRUCTOR"
    TEACHING_ASSISTANT = "TEACHING_ASSISTANT"
    STUDENT = "STUDENT"
    ACADEMIC_ADMIN = "ACADEMIC_ADMIN"


class AuditAction(str, Enum):
    ENROLLMENT_CREATED = "ENROLLMENT_CREATED"
    ENROLLMENT_GROUPED = "ENROLLMENT_GROUPED"
    ENROLLMENT_WITHDRAWN = "ENROLLMENT_WITHDRAWN"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    REFUND_APPROVED = "REFUND_APPROVED"
    REFUND_REJECTED = "REFUND_REJECTED"


class AuditSubjectType(str, Enum):
    ENROLLMENT = "ENROLLMENT"
    REFUND_REQUEST = "REFUND_REQUEST"


# ──────────────────────────────────────────────────────────
# Entity TypedDicts — common_fields=true (id, created_at, updated_at, version)
# ──────────────────────────────────────────────────────────

class Course(TypedDict, total=False):
    id: str
    title: str
    instructor_id: str
    list_price_cents: int
    discount_percent: int
    status: str
    posture: str
    published_syllabus_revision_id: Optional[str]
    total_chapters: int
    total_video_seconds: int
    enrollment_count: int
    created_at: str
    updated_at: str
    version: int


class Chapter(TypedDict, total=False):
    id: str
    course_id: str
    title: str
    ordinal: int
    video_duration_seconds: int
    required_for_completion: bool
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    bio: str
    availability_windows: List[dict]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    course_id: str
    student_id: str
    class_group_id: Optional[str]
    payment_status: str
    learning_status: str
    paid_amount_cents: int
    enrolled_at: str
    chapter_completion_percent: float
    watch_duration_percent: float
    progress_percent: float
    attendance_count: int
    refund_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ClassGroup(TypedDict, total=False):
    id: str
    course_id: str
    name: str
    capacity: int
    ta_instructor_id: Optional[str]
    enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class LiveClass(TypedDict, total=False):
    id: str
    course_id: str
    chapter_id: Optional[str]
    instructor_id: str
    room_id: str
    start_ts: int
    end_ts: int
    status: str
    checkin_code: Optional[str]
    recording_playback_enabled: bool
    original_live_class_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeaveRequest(TypedDict, total=False):
    id: str
    enrollment_id: str
    live_class_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    course_id: str
    chapter_id: Optional[str]
    title: str
    format: str
    due_ts: int
    max_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict, total=False):
    id: str
    assignment_id: str
    enrollment_id: str
    payload_text: Optional[str]
    payload_file_url: Optional[str]
    payload_code: Optional[str]
    status: str
    revision_count: int
    plagiarism_score: float
    score: Optional[int]
    feedback: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict, total=False):
    id: str
    enrollment_id: str
    course_id: str
    requested_at: str
    status: str
    provisional_amount_cents: int
    provisional_progress_percent: float
    final_amount_cents: Optional[int]
    materials_kit_count: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ──────────────────────────────────────────────────────────
# Entity TypedDicts — common_fields=false (id, created_at only — no updated_at, no version)
# ──────────────────────────────────────────────────────────

class SyllabusRevision(TypedDict, total=False):
    id: str
    course_id: str
    revision_number: int
    outline: List[dict]
    pricing_snapshot_cents: int
    discount_snapshot_percent: int
    created_at: str


class Announcement(TypedDict, total=False):
    id: str
    class_group_id: str
    course_id: str
    author_role: str
    author_id: str
    body: str
    created_at: str


class Attendance(TypedDict, total=False):
    id: str
    live_class_id: str
    enrollment_id: str
    mark: str
    checkin_method: str
    checkin_ts: Optional[int]
    code_provided: Optional[str]
    created_at: str


class WatchSession(TypedDict, total=False):
    id: str
    enrollment_id: str
    chapter_id: str
    seconds_watched: int
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    action: str
    subject_type: str
    subject_id: str
    detail: dict
    created_at: str


class Clock(TypedDict, total=False):
    id: str
    now_ts: int
    created_at: str
