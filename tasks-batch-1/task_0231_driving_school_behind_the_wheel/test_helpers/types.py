"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SCHOOL_ADMIN = "SchoolAdmin"
    INSTRUCTOR = "Instructor"
    STUDENT = "Student"
    GUARDIAN = "Guardian"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class StudentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ENROLLED = "ENROLLED"
    PERMITTED = "PERMITTED"
    ROAD_READY = "ROAD_READY"
    CERTIFIED = "CERTIFIED"
    LICENSED = "LICENSED"


class GuardianConsentStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class EnrollmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class LessonStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class LessonType(str, Enum):
    CLASSROOM = "CLASSROOM"
    ONLINE = "ONLINE"
    ROAD = "ROAD"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RefundMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    SCHEDULE_TIER = "SCHEDULE_TIER"


class GuardianRelationship(str, Enum):
    PARENT = "PARENT"
    LEGAL_GUARDIAN = "LEGAL_GUARDIAN"


class WalletReason(str, Enum):
    REFUND_CREDIT = "REFUND_CREDIT"
    NO_SHOW_DEBIT = "NO_SHOW_DEBIT"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"


# ---------------------------------------------------------------------------
# Full resources (carry id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class Student(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    is_minor: bool
    permit_number: Optional[str]
    status: str
    completed_classroom_hours: float
    completed_online_hours: float
    completed_road_hours: float
    scheduled_road_hours: float
    readiness_score: float
    no_show_count: int
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class GuardianConsent(TypedDict, total=False):
    id: str
    student_id: str
    guardian_name: str
    guardian_email: str
    relationship: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    student_id: str
    package_id: str
    promo_code: Optional[str]
    status: str
    final_price_cents: int
    amount_paid_cents: int
    refund_method: Optional[str]
    refunded_cents: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    certified_road: bool
    hourly_rate_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    plate: str
    dual_control: bool
    prep_buffer_minutes: int
    out_of_service: bool
    created_at: str
    updated_at: str
    version: int


class Lesson(TypedDict, total=False):
    id: str
    student_id: str
    enrollment_id: str
    instructor_id: Optional[str]
    vehicle_id: Optional[str]
    lesson_type: str
    start_at: str
    end_at: str
    duration_hours: float
    status: str
    instructor_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    student_id: str
    enrollment_id: str
    dmv_reference: Optional[str]
    readiness_score_at_issue: float
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Ledger-style resources (carry ONLY id + created_at — no updated_at, no version)
# ---------------------------------------------------------------------------
class CoursePackage(TypedDict, total=False):
    id: str
    code: str
    name: str
    price_cents: int
    enrollment_fee_cents: int
    included_classroom_hours: float
    included_online_hours: float
    included_road_hours: float
    bundle_discount_cents: int
    active: bool
    created_at: str


class NoShowStrike(TypedDict, total=False):
    id: str
    student_id: str
    lesson_id: str
    strike_index: int
    fee_charged_cents: int
    created_at: str


class WalletEntry(TypedDict, total=False):
    id: str
    student_id: str
    amount_cents: int
    reason: str
    enrollment_id: Optional[str]
    created_at: str
