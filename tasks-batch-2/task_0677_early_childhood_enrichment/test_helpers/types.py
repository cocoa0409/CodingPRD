"""Domain types: entity TypedDicts, status enums, role enum.

All names use PRD terminology for the Early Childhood Enrichment API.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ChildStatus(str, Enum):
    ENROLLED_ELIGIBLE = "ENROLLED_ELIGIBLE"
    WITHDRAWN = "WITHDRAWN"


class MembershipTier(str, Enum):
    CORE = "CORE"
    PLUS = "PLUS"
    UNLIMITED = "UNLIMITED"


class MembershipStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CANCELLED = "CANCELLED"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ClassSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class EnrollmentKind(str, Enum):
    TRIAL = "TRIAL"
    RECURRING = "RECURRING"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class AttendanceOutcome(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"


class MakeupCreditStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class BookingType(str, Enum):
    BIRTHDAY_PARTY = "BIRTHDAY_PARTY"
    OPEN_GYM = "OPEN_GYM"


class FacilityBookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class UserRole(str, Enum):
    STUDIO_ADMIN = "StudioAdmin"
    FRONT_DESK_STAFF = "FrontDeskStaff"
    PARENT = "Parent"


# --------------------------------------------------------------------------
# Entity TypedDicts
#
# Entities carrying the full common-field set (id, created_at, updated_at,
# version): Family, Child, Membership, Program, Room, Instructor,
# ClassSession, Enrollment, FacilityBooking, Invoice.
#
# Leaner entities (id + created_at only, NO updated_at, NO version):
# AttendanceRecord, MakeupCredit.
# --------------------------------------------------------------------------
class Family(TypedDict):
    id: str
    account_email: str
    primary_contact_name: str
    child_count: int
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict):
    id: str
    family_id: str
    full_name: str
    birth_date: str
    current_level: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    family_id: str
    tier: str
    status: str
    cycle_anchor_day: int
    current_cycle_start: Optional[str]
    makeup_credit_balance: int
    monthly_base_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict):
    id: str
    name: str
    level_index: int
    min_age_months: int
    max_age_months: int
    participation_required: bool
    tuition_cents: int
    next_program_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    name: str
    physical_capacity: int
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    certified_level_indices: List[int]
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    program_id: str
    room_id: str
    instructor_id: str
    start_at: str
    end_at: str
    capacity: int
    enrolled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    child_id: str
    session_id: str
    membership_id: str
    kind: str
    status: str
    waitlist_seq: Optional[int]
    redeemed_credit_id: Optional[str]
    residual_owed_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — id + created_at only
class AttendanceRecord(TypedDict):
    id: str
    enrollment_id: str
    session_id: str
    outcome: str
    created_at: str


# common_fields: false — id + created_at only
class MakeupCredit(TypedDict):
    id: str
    membership_id: str
    issued_tuition_cents: int
    status: str
    expires_at: str
    created_at: str


class FacilityBooking(TypedDict):
    id: str
    room_id: str
    family_id: str
    booking_type: str
    start_at: str
    end_at: str
    head_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    membership_id: str
    cycle_start: str
    subtotal_cents: int
    sibling_discount_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
