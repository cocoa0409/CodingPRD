"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity and lifecycle definitions. All entities in this
system are mutable bookkeeping records (PRD 2.4), so every entity carries
id + created_at + updated_at + version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    STUDIO_ADMIN = "StudioAdmin"
    INSTRUCTOR = "Instructor"
    PARENT_GUARDIAN = "ParentGuardian"
    BILLING_CLERK = "BillingClerk"


# --------------------------------------------------------------------------
# Instrument enum (PRD 3.1)
# --------------------------------------------------------------------------
class Instrument(str, Enum):
    PIANO = "PIANO"
    VIOLIN = "VIOLIN"
    GUITAR = "GUITAR"
    DRUMS = "DRUMS"
    VOICE = "VOICE"
    CELLO = "CELLO"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class StudioStatus(str, Enum):
    OPEN = "OPEN"


class FamilyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SkillLevel(str, Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EnrollmentLifecycleStatus(str, Enum):
    PENDING_MATCH = "PENDING_MATCH"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CANCELLED = "CANCELLED"


class EnrollmentBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    PAST_DUE = "PAST_DUE"


class OccurrenceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED_LATE = "CANCELLED_LATE"
    CANCELLED_NOTICE = "CANCELLED_NOTICE"
    MAKEUP_PENDING = "MAKEUP_PENDING"


class MakeupCreditStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class PaymentMethod(str, Enum):
    WALLET = "WALLET"
    AUTOPAY = "AUTOPAY"


class PaymentFailureReason(str, Enum):
    NONE = "NONE"
    INSUFFICIENT_FUNDS = "INSUFFICIENT_FUNDS"


class RecitalEventStatus(str, Enum):
    REG_OPEN = "REG_OPEN"
    REG_CLOSED = "REG_CLOSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN = "WITHDRAWN"


class RentalStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry common fields id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Studio(TypedDict):
    id: str
    name: str
    current_utc: str
    family_discount_tiers: list
    makeup_credit_cap_per_enrollment: int
    cancellation_notice_hours: int
    makeup_credit_valid_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    studio_id: str
    household_name: str
    autopay_enabled: bool
    wallet_balance_cents: int
    active_enrollment_count: int
    family_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    family_id: str
    full_name: str
    skill_level: str
    total_practice_minutes: int
    weighted_progress_score: float
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    studio_id: str
    full_name: str
    instruments: list
    weekly_availability: list
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    studio_id: str
    room_name: str
    supported_instruments: list
    turnover_buffer_min: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    studio_id: str
    family_id: str
    student_id: str
    instructor_id: str
    room_id: str
    instrument: str
    weekday: int
    start_min: int
    duration_min: int
    lifecycle_status: str
    billing_status: str
    monthly_tuition_cents: int
    created_at: str
    updated_at: str
    version: int


class LessonOccurrence(TypedDict):
    id: str
    enrollment_id: str
    room_id: str
    instructor_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    is_makeup: bool
    consumed_credit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MakeupCredit(TypedDict):
    id: str
    enrollment_id: str
    origin_occurrence_id: str
    issued_utc: str
    expires_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TuitionInvoice(TypedDict):
    id: str
    family_id: str
    enrollment_id: str
    billing_period: str
    provisional_amount_cents: int
    finalized_amount_cents: int
    rental_surcharge_cents: int
    amount_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    invoice_id: str
    family_id: str
    amount_cents: int
    method: str
    status: str
    failure_reason: str
    created_at: str
    updated_at: str
    version: int


class RecitalEvent(TypedDict):
    id: str
    studio_id: str
    title: str
    venue_capacity: int
    event_start_utc: str
    registration_deadline_utc: str
    confirmed_count: int
    waitlist_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecitalRegistration(TypedDict):
    id: str
    recital_event_id: str
    student_id: str
    registered_utc: str
    performance_order: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstrumentRental(TypedDict):
    id: str
    studio_id: str
    family_id: str
    instrument_unit_code: str
    period_fee_cents: int
    rental_start_utc: str
    rental_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int
