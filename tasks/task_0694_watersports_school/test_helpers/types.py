"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Watersports School API PRD. Entities that carry the full
common-field quartet (id, created_at, updated_at, version) are modelled with
those four fields; the CertificationCard is the single lean entity carrying
only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---------------------------------------------------
class UserRole(str, Enum):
    SCHOOL_ADMIN = "SchoolAdmin"
    INSTRUCTOR = "Instructor"
    STUDENT = "Student"


# --- Status enums -----------------------------------------------------------
class SchoolOperatingStatus(str, Enum):
    OPEN = "OPEN"
    STORM_CLOSED = "STORM_CLOSED"


class CourseDiscipline(str, Enum):
    SURF = "SURF"
    SAIL = "SAIL"
    WINDSURF = "WINDSURF"
    KAYAK = "KAYAK"


class CourseKind(str, Enum):
    LESSON = "LESSON"
    CERTIFICATION = "CERTIFICATION"


class CourseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EquipmentType(str, Enum):
    BOARD = "BOARD"
    SAIL_RIG = "SAIL_RIG"
    KAYAK = "KAYAK"


class RequiredEquipmentType(str, Enum):
    BOARD = "BOARD"
    SAIL_RIG = "SAIL_RIG"
    KAYAK = "KAYAK"
    NONE = "NONE"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RENTED = "RENTED"
    MAINTENANCE = "MAINTENANCE"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SwimTestStatus(str, Enum):
    UNTESTED = "UNTESTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class WaiverStatusDerived(str, Enum):
    NONE = "NONE"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class WaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class MembershipTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class EnrollmentProgressStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class EnrollmentPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WEATHER_HOLD = "WEATHER_HOLD"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SessionBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class RentalStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts ------------------------------------------------------
# All entities below carry the full quartet EXCEPT CertificationCard.

class School(TypedDict):
    id: str
    name: str
    timezone: str
    storm_advisory_active: bool
    operating_status: str
    open_session_count: int
    created_at: str
    updated_at: str
    version: int


class Course(TypedDict):
    id: str
    school_id: str
    discipline: str
    title: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CourseLevel(TypedDict):
    id: str
    course_id: str
    school_id: str
    rank: int
    name: str
    max_students_per_instructor: int
    base_price_cents: int
    min_age: int
    requires_swim_test: bool
    required_equipment_type: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    school_id: str
    full_name: str
    certified_disciplines: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentItem(TypedDict):
    id: str
    school_id: str
    equipment_type: str
    asset_tag: str
    hourly_rate_cents: int
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    school_id: str
    full_name: str
    birthdate: str
    age_years: int
    swim_test_status: str
    waiver_status: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    student_id: str
    signed_by: str
    is_guardian: bool
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    student_id: str
    tier: str
    status: str
    makeup_credit_balance: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    school_id: str
    student_id: str
    course_level_id: str
    membership_id: Optional[str]
    planned_sessions: int
    party_size: int
    progress_status: str
    payment_status: str
    estimated_price_cents: int
    final_price_cents: Optional[int]
    refund_cents: Optional[int]
    attended_count: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    school_id: str
    course_level_id: str
    instructor_id: str
    starts_at: str
    ends_at: str
    tide_window_start: str
    tide_window_end: str
    capacity: int
    enrolled_count: int
    required_instructors: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionBooking(TypedDict):
    id: str
    session_id: str
    enrollment_id: str
    is_makeup: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RentalAgreement(TypedDict):
    id: str
    school_id: str
    student_id: str
    equipment_item_id: str
    session_id: Optional[str]
    starts_at: str
    ends_at: str
    rental_fee_cents: int
    deposit_held_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# CertificationCard is the lean entity — only id + created_at among common fields.
class CertificationCard(TypedDict):
    id: str
    student_id: str
    enrollment_id: str
    course_level_id: str
    discipline: str
    card_number: str
    issued_at: str
    created_at: str
