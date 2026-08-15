"""Domain types: entity TypedDicts, status enums, role enum (PRD §2 and §3)."""
from enum import Enum
from typing import Optional, TypedDict


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class ClassSessionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CancellationReason(str, Enum):
    LOW_ENROLLMENT = "LOW_ENROLLMENT"
    ADMIN = "ADMIN"


class ContractStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    VOID = "VOID"
    TERMINATED = "TERMINATED"
    SETTLED = "SETTLED"


class SettlementBasis(str, Enum):
    ENROLLMENT_BASIS = "ENROLLMENT_BASIS"
    ATTENDANCE_BASIS = "ATTENDANCE_BASIS"


class ResidencyStatus(str, Enum):
    PENDING = "PENDING"
    RESIDENT = "RESIDENT"
    NONRESIDENT = "NONRESIDENT"


class SafetyFormStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ScholarshipStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO_REQUESTED = "MORE_INFO_REQUESTED"
    RESUBMITTED = "RESUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    WAIVED = "WAIVED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class DropReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    NO_SHOW = "NO_SHOW"
    PAYMENT_TIMEOUT = "PAYMENT_TIMEOUT"
    LOW_ENROLLMENT = "LOW_ENROLLMENT"
    ADMIN = "ADMIN"


class PaymentType(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class PaymentMethod(str, Enum):
    EXTERNAL = "EXTERNAL"
    ACCOUNT_CREDIT = "ACCOUNT_CREDIT"


class PaymentTransactionStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class AttendanceStatus(str, Enum):
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    EXCUSED = "EXCUSED"


class UserRole(str, Enum):
    HOUSEHOLD_MANAGER = "HouseholdManager"
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    FRONT_DESK_STAFF = "FrontDeskStaff"
    INSTRUCTOR = "Instructor"
    SCHOLARSHIP_REVIEWER = "ScholarshipReviewer"
    FINANCE_OFFICER = "FinanceOfficer"


class Season(TypedDict, total=False):
    id: str
    name: str
    start_date: str
    end_date: str
    resident_opens_at: str
    general_opens_at: str
    registration_closes_at: str
    family_discount_threshold: int
    family_discount_pct: int
    scholarship_budget_cents: int
    scholarship_committed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    category: str
    min_age: int
    max_age: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict, total=False):
    id: str
    program_id: str
    instructor_id: str
    title: str
    capacity: int
    min_enrollment: int
    fee_resident_cents: int
    fee_nonresident_cents: int
    enrollment_check_at: str
    enrolled_count: int
    waitlist_count: int
    status: str
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClassMeeting(TypedDict, total=False):
    id: str
    session_id: str
    room_id: str
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


class InstructorContract(TypedDict, total=False):
    id: str
    session_id: str
    instructor_id: str
    revenue_share_bp: int
    guarantee_min_cents: int
    cancellation_guarantee_cents: int
    settlement_basis: str
    settlement_headcount: Optional[int]
    settlement_amount_cents: Optional[int]
    payout_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict, total=False):
    id: str
    account_name: str
    residency_status: str
    account_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    household_id: str
    full_name: str
    birth_date: str
    created_at: str
    updated_at: str
    version: int


class SafetyForm(TypedDict, total=False):
    id: str
    participant_id: str
    season_id: str
    emergency_contact_name: str
    emergency_contact_phone: str
    medical_notes: str
    signer_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipApplication(TypedDict, total=False):
    id: str
    household_id: str
    season_id: str
    household_size: int
    annual_income_cents: int
    statement: str
    info_request_note: Optional[str]
    approved_pct: Optional[int]
    estimated_commitment_cents: Optional[int]
    reviewed_by: Optional[str]
    decided_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    session_id: str
    participant_id: str
    household_id: str
    residency_at_registration: str
    scholarship_pct_applied: int
    family_discount_applied: bool
    fee_charged_cents: int
    net_paid_cents: int
    refund_total_cents: int
    enrollment_status: str
    payment_status: str
    drop_reason: Optional[str]
    waitlisted_at: Optional[str]
    promoted_at: Optional[str]
    payment_due_at: Optional[str]
    consecutive_absences: int
    created_at: str
    updated_at: str
    version: int


class PaymentTransaction(TypedDict, total=False):
    id: str
    registration_id: str
    type: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict, total=False):
    id: str
    meeting_id: str
    registration_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
