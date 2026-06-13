"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and lifecycles described in the Trusted Traveler
Enrollment PRD (programs, centers, slots, applicants, applications,
background checks, appointments, biometric captures, KTNs, appeals,
redress cases, fee transactions, audit events).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Status enums -----------------------------------------------------------

class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VETTING = "VETTING"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    INTERVIEW_COMPLETE = "INTERVIEW_COMPLETE"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    APPEAL_PENDING = "APPEAL_PENDING"
    WITHDRAWN = "WITHDRAWN"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    REVIEW = "REVIEW"
    ADVERSE = "ADVERSE"


class AppointmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class AppointmentSlotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class KtnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class AppealStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class RedressStatus(str, Enum):
    FILED = "FILED"
    RESOLVED = "RESOLVED"


class RedressResolution(str, Enum):
    CLEARED = "CLEARED"
    CONFIRMED = "CONFIRMED"


class CenterStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class BiometricStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ProgramCode(str, Enum):
    PRECHECK = "PRECHECK"
    GLOBAL_ENTRY = "GLOBAL_ENTRY"


class Citizenship(str, Enum):
    US_CITIZEN = "US_CITIZEN"
    LPR = "LPR"
    NONIMMIGRANT = "NONIMMIGRANT"


class FeeTransactionKind(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    VETTING_OFFICER = "VettingOfficer"
    ENROLLMENT_OFFICER = "EnrollmentOfficer"
    APPEALS_OFFICER = "AppealsOfficer"
    SCHEDULING_ADMIN = "SchedulingAdmin"
    AUDITOR = "Auditor"


# --- Entity TypedDicts ------------------------------------------------------
# Entities with the standard common fields carry id, created_at, updated_at,
# and version. The two immutable event-log records (FeeTransaction, AuditEvent)
# carry only id and created_at.

class Program(TypedDict):
    id: str
    code: str
    name: str
    base_fee_cents: int
    validity_years: int
    vetting_risk_threshold: int
    vetting_deny_threshold: int
    redress_min_score: int
    renewal_window_days: int
    created_at: str
    updated_at: str
    version: int


class EnrollmentCenter(TypedDict):
    id: str
    program_code: str
    name: str
    daily_interview_capacity: int
    buffer_minutes: int
    lane_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AppointmentSlot(TypedDict):
    id: str
    center_id: str
    lane_index: int
    starts_at: str
    ends_at: str
    status: str
    held_by_appointment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    citizenship: str
    disqualifying_flag: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    program_code: str
    renews_from_application_id: Optional[str]
    fee_due_cents: int
    fee_paid_cents: int
    adverse_reason: Optional[str]
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    application_id: str
    criminal_hits: int
    watchlist_hits: int
    prior_revocations: int
    risk_score: int
    redress_offset_applied: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    application_id: str
    slot_id: str
    center_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BiometricCapture(TypedDict):
    id: str
    appointment_id: str
    application_id: str
    fingerprint_quality: int
    photo_captured: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class KnownTravelerNumber(TypedDict):
    id: str
    application_id: str
    applicant_id: str
    ktn_value: str
    issued_at: str
    expires_at: str
    renews_from_ktn_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    application_id: str
    filed_reason: str
    decided_by_user_id: Optional[str]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RedressCase(TypedDict):
    id: str
    application_id: str
    trip_number: str
    match_strength_score: int
    resolution: Optional[str]
    risk_offset: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable event-log records: id + created_at only (no updated_at, no version).
class FeeTransaction(TypedDict):
    id: str
    application_id: str
    kind: str
    amount_cents: int
    reason: Optional[str]
    created_at: str


class AuditEvent(TypedDict):
    id: str
    application_id: str
    actor_user_id: str
    actor_role: str
    event_type: str
    detail: str
    created_at: str
