"""Domain types: entity TypedDicts, status enums, role enum.

All entities here carry the common fields id/created_at/updated_at/version
because every resource in this API is mutable and version-tracked.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────

class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class InstructorRank(str, Enum):
    INSTRUCTOR = "INSTRUCTOR"
    CHIEF_INSTRUCTOR = "CHIEF_INSTRUCTOR"


class EnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    DROPPED = "DROPPED"


class ClassSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class AttendanceStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class PromotionTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED_PENDING_SIGNOFF = "PASSED_PENDING_SIGNOFF"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    FULFILLED = "FULFILLED"
    TERMINATED = "TERMINATED"


class InvoiceStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"
    VOID = "VOID"


class InvoiceKind(str, Enum):
    TUITION = "TUITION"
    TEST_FEE = "TEST_FEE"
    PRO_SHOP = "PRO_SHOP"
    BUYOUT = "BUYOUT"
    PRIVATE_LESSON = "PRIVATE_LESSON"


class PrivateLessonStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TournamentRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WITHDRAWN = "WITHDRAWN"


class TournamentDivision(str, Enum):
    YOUTH = "YOUTH"
    TEEN = "TEEN"
    ADULT = "ADULT"
    MASTERS = "MASTERS"


class ProShopOrderStatus(str, Enum):
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class Discipline(str, Enum):
    KARATE = "KARATE"
    BJJ = "BJJ"
    TAEKWONDO = "TAEKWONDO"
    JUDO = "JUDO"
    MUAY_THAI = "MUAY_THAI"


class UserRole(str, Enum):
    FRONT_DESK = "FrontDesk"
    INSTRUCTOR = "Instructor"
    CHIEF_INSTRUCTOR = "ChiefInstructor"
    MEMBER = "Member"


# ─── Entity TypedDicts (all mutable: id + created_at + updated_at + version) ───

class Program(TypedDict):
    id: str
    name: str
    discipline: str
    base_monthly_tuition_cents: int
    test_fee_cents: int
    min_attendance_for_test: int
    min_days_in_rank: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BeltRank(TypedDict):
    id: str
    program_id: str
    code: str
    rank_order: int
    next_rank_code: Optional[str]
    is_entry_rank: bool
    requires_chief_signoff: bool
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    surname: str
    billing_email: str
    active_member_count: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    family_id: Optional[str]
    full_name: str
    email: str
    date_of_birth: str
    account_status: str
    waiver_signed: bool
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    email: str
    rank_level: str
    is_available: bool
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    member_id: str
    program_id: str
    current_rank_code: str
    rank_attendance_count: int
    rank_acquired_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    program_id: str
    instructor_id: str
    starts_at: str
    ends_at: str
    capacity: int
    confirmed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Attendance(TypedDict):
    id: str
    enrollment_id: str
    class_session_id: str
    status: str
    counts_toward_rank: bool
    created_at: str
    updated_at: str
    version: int


class PromotionTest(TypedDict):
    id: str
    enrollment_id: str
    examiner_instructor_id: str
    target_rank_code: str
    scheduled_for: str
    status: str
    score: Optional[int]
    chief_signoff_instructor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    member_id: str
    program_id: str
    term_months: int
    billing_anchor_day: int
    months_billed: int
    status: str
    locked_family_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    member_id: str
    contract_id: Optional[str]
    kind: str
    amount_due_cents: int
    status: str
    due_at: str
    created_at: str
    updated_at: str
    version: int


class PrivateLesson(TypedDict):
    id: str
    member_id: str
    instructor_id: str
    starts_at: str
    ends_at: str
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TournamentRegistration(TypedDict):
    id: str
    member_id: str
    enrollment_id: str
    tournament_name: str
    event_date: str
    division: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProShopOrder(TypedDict):
    id: str
    member_id: str
    line_items: List[dict]
    gross_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
