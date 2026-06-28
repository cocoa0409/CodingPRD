"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry id, created_at, updated_at, and version
(see PRD Section 2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SCHOOL_ADMIN = "SchoolAdmin"
    BILLING_ADMIN = "BillingAdmin"
    INSTRUCTOR = "Instructor"
    PARENT = "Parent"


class LocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AccountStanding(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"


class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ClassSessionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EnrollmentStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    WITHDRAWN = "WITHDRAWN"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceVariant(str, Enum):
    FORWARD_LOOKING = "FORWARD_LOOKING"
    CHRONOLOGICAL = "CHRONOLOGICAL"


class MakeupCreditStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class MakeupCreditReason(str, Enum):
    SKIP = "SKIP"
    ABSENCE = "ABSENCE"
    LEVEL_TRANSFER_DISRUPTION = "LEVEL_TRANSFER_DISRUPTION"


class MakeupBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    ATTENDED = "ATTENDED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Location(TypedDict):
    id: str
    name: str
    timezone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Level(TypedDict):
    id: str
    name: str
    sequence_order: int
    next_level_id: Optional[str]
    min_age_months: int
    max_age_months: int
    max_students_per_instructor: int
    monthly_tuition_cents: int
    readiness_threshold: float
    created_at: str
    updated_at: str
    version: int


class Skill(TypedDict):
    id: str
    level_id: str
    name: str
    weight: float
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    certified_level_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Parent(TypedDict):
    id: str
    full_name: str
    email: str
    account_standing: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    parent_id: str
    full_name: str
    birthdate: str
    current_level_id: str
    age_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    location_id: str
    level_id: str
    instructor_id: str
    lane_number: int
    day_of_week: int
    start_minute: int
    end_minute: int
    capacity: int
    enrolled_count: int
    waitlist_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    class_session_id: str
    joined_at: Optional[str]
    tuition_basis_cents: int
    is_prorated_first_cycle: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    parent_id: str
    cycle_start: str
    cycle_end: str
    variant: str
    line_items: list
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MakeupCredit(TypedDict):
    id: str
    student_id: str
    origin_enrollment_id: str
    reason: str
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MakeupBooking(TypedDict):
    id: str
    makeup_credit_id: str
    student_id: str
    target_class_session_id: str
    occurrence_date: str
    occurrence_start_minute: int
    occurrence_end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Assessment(TypedDict):
    id: str
    enrollment_id: str
    student_id: str
    assessed_level_id: str
    skill_scores: list
    mastered_count: int
    weighted_score: float
    strict_ready: bool
    holistic_ready: bool
    status: str
    created_at: str
    updated_at: str
    version: int
