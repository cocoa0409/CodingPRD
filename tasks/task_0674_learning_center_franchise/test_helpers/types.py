"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Status enums (one per entity with a state machine) ---

class CenterStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    OPERATING = "OPERATING"
    SUSPENDED = "SUSPENDED"


class FranchiseAgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class SubjectStatus(str, Enum):
    ACTIVE = "ACTIVE"


class EnrollmentStatus(str, Enum):
    PLACEMENT_PENDING = "PLACEMENT_PENDING"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class WorksheetStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    GRADED = "GRADED"
    RETRY = "RETRY"
    MASTERED = "MASTERED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AttendanceRecordStatus(str, Enum):
    BOOKED = "BOOKED"
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class PlacementPolicy(str, Enum):
    STRICT = "STRICT"
    SUPPORTIVE = "SUPPORTIVE"


class RoyaltyBasis(str, Enum):
    ROYALTY_FLOOR = "ROYALTY_FLOOR"
    COMBINED_FLOOR = "COMBINED_FLOOR"


class UserRole(str, Enum):
    FRANCHISE_ADMIN = "FranchiseAdmin"
    CENTER_DIRECTOR = "CenterDirector"
    INSTRUCTOR = "Instructor"
    PARENT = "Parent"


# --- Entity TypedDicts.  All entities carry common_fields: true,
#     so each has id + created_at + updated_at + version. ---

class Center(TypedDict):
    id: str
    name: str
    territory_code: str
    instructor_ratio_cap: int
    enrollment_fee_cents: int
    monthly_tuition_cents: int
    status: str
    active_enrollment_count: int
    created_at: str
    updated_at: str
    version: int


class FranchiseAgreement(TypedDict):
    id: str
    center_id: str
    royalty_rate_bps: int
    marketing_fee_bps: int
    minimum_monthly_royalty_cents: int
    royalty_basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subject(TypedDict):
    id: str
    center_id: str
    name: str
    code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CurriculumLevel(TypedDict):
    id: str
    subject_id: str
    rank: int
    label: str
    prereq_level_id: Optional[str]
    worksheets_to_master: int
    mastery_score_threshold: int
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    center_id: str
    contact_email: str
    contact_name: str
    wallet_credit_cents: int
    sibling_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    family_id: str
    full_name: str
    birthdate: str
    enrollment_fee_charged: bool
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    center_id: str
    student_id: str
    subject_id: str
    placement_level_id: Optional[str]
    current_level_id: Optional[str]
    diagnostic_raw_score: Optional[int]
    status: str
    mastered_sets_in_level: int
    monthly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Worksheet(TypedDict):
    id: str
    enrollment_id: str
    level_id: str
    set_number: int
    score: Optional[int]
    attempt_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    center_id: str
    instructor_user_id: str
    start_at: str
    end_at: str
    seat_cap: int
    booked_seat_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    id: str
    session_id: str
    enrollment_id: str
    status: str
    marked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    family_id: str
    center_id: str
    period_month: str
    enrollment_fee_component_cents: int
    tuition_component_cents: int
    wallet_applied_cents: int
    total_due_cents: int
    royalty_owed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
