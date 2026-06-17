"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD exactly. Two entities are deliberately leaner:
Syllabus (immutable config) and DepositTransaction (append-only ledger event)
carry only id + created_at — no updated_at, no version.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ──────────────────────────────────────────────────────────────────────────
# Roles
# ──────────────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    SCHOOL_ADMIN = "SchoolAdmin"
    DISPATCHER = "Dispatcher"
    STUDENT = "Student"
    INSTRUCTOR = "Instructor"
    MECHANIC = "Mechanic"


# ──────────────────────────────────────────────────────────────────────────
# Status enums
# ──────────────────────────────────────────────────────────────────────────
class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AircraftStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    GROUNDED = "GROUNDED"
    RETIRED = "RETIRED"


class BillingBasis(str, Enum):
    HOBBS = "HOBBS"
    TACH = "TACH"


class EnrollmentStatus(str, Enum):
    PENDING_CLEARANCE = "PENDING_CLEARANCE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class MedicalStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"


class TsaStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    DENIED = "DENIED"


class DepositTxnType(str, Enum):
    DEPOSIT = "DEPOSIT"
    HOLD = "HOLD"
    RELEASE = "RELEASE"
    CONSUME = "CONSUME"


class SquawkStatus(str, Enum):
    OPEN = "OPEN"
    DEFERRED = "DEFERRED"
    RESOLVED = "RESOLVED"


class BookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class LessonType(str, Enum):
    DUAL = "DUAL"
    SOLO = "SOLO"


class FlightLogStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    VOID = "VOID"


class StageCheckStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"


class EndorsementCode(str, Enum):
    SOLO = "SOLO"
    XC = "XC"
    COMPLEX = "COMPLEX"
    TAILWHEEL = "TAILWHEEL"


class EndorsementStatus(str, Enum):
    VALID = "VALID"
    REVOKED = "REVOKED"


# ──────────────────────────────────────────────────────────────────────────
# Entity TypedDicts — versioned (id + created_at + updated_at + version)
# ──────────────────────────────────────────────────────────────────────────
class Student(TypedDict):
    id: str
    full_name: str
    email: str
    deposit_balance_cents: int
    deposit_held_cents: int
    deposit_consumed_cents: int
    no_show_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    email: str
    cfi_rate_cents_per_hour: int
    authorized_endorsement_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    tail_number: str
    model: str
    is_complex: bool
    rental_rate_cents_per_hour: int
    billing_basis: str
    current_hobbs: float
    current_tach: float
    initial_hobbs: float
    initial_tach: float
    open_squawk_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    student_id: str
    syllabus_id: str
    medical_status: str
    medical_expiry_date: Optional[str]
    tsa_status: str
    logged_dual_hours: float
    logged_solo_hours: float
    current_stage_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Squawk(TypedDict):
    id: str
    aircraft_id: str
    description: str
    is_grounding: bool
    reported_by_instructor_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    enrollment_id: str
    aircraft_id: str
    instructor_id: Optional[str]
    lesson_type: str
    start_at: str
    end_at: str
    estimated_hours: float
    estimated_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FlightLog(TypedDict):
    id: str
    booking_id: str
    enrollment_id: str
    aircraft_id: str
    instructor_id: Optional[str]
    hobbs_start: float
    hobbs_end: float
    tach_start: float
    tach_end: float
    landings: int
    billed_hours: float
    aircraft_charge_cents: int
    instructor_charge_cents: int
    total_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StageCheck(TypedDict):
    id: str
    enrollment_id: str
    examiner_instructor_id: str
    stage_index: int
    retry_of_stage_check_id: Optional[str]
    result_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict):
    id: str
    enrollment_id: str
    instructor_id: str
    endorsement_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ──────────────────────────────────────────────────────────────────────────
# Entity TypedDicts — lean (id + created_at only)
# ──────────────────────────────────────────────────────────────────────────
class Syllabus(TypedDict):
    id: str
    name: str
    required_dual_hours: float
    required_solo_hours: float
    stage_count: int
    min_deposit_cents: int
    created_at: str


class DepositTransaction(TypedDict):
    id: str
    student_id: str
    txn_type: str
    amount_cents: int
    booking_id: Optional[str]
    flight_log_id: Optional[str]
    memo: Optional[str]
    created_at: str
