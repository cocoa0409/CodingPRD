"""Domain types: entity TypedDicts, status enums, and the role enum.

All names follow the PRD's vocabulary for the online tutoring marketplace.
Every entity in this system is mutable and therefore carries the four common
fields id / created_at / updated_at / version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TRUST_OFFICER = "TrustOfficer"
    TUTOR = "Tutor"
    PARENT_GUARDIAN = "ParentGuardian"
    ARBITER = "Arbiter"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class SubjectStatus(str, Enum):
    ACTIVE = "ACTIVE"


class SubjectCategory(str, Enum):
    STEM = "STEM"
    LANGUAGE = "LANGUAGE"
    HUMANITIES = "HUMANITIES"
    TEST_PREP = "TEST_PREP"
    MUSIC = "MUSIC"


class CommissionPolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class TutorVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class CredentialStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class CredentialKind(str, Enum):
    DEGREE = "DEGREE"
    CERTIFICATION = "CERTIFICATION"
    TEACHING_LICENSE = "TEACHING_LICENSE"
    TRANSCRIPT = "TRANSCRIPT"


class TutorSubjectTagStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class ParentAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"


class StudentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class BookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SessionSettlementStatus(str, Enum):
    DELIVERED = "DELIVERED"
    SETTLED = "SETTLED"
    REFUND_OPEN = "REFUND_OPEN"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class SessionDeliveryStatus(str, Enum):
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"


class SettlementStatus(str, Enum):
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"
    PARTIALLY_REVERSED = "PARTIALLY_REVERSED"


class RefundCaseStatus(str, Enum):
    PARENT_PROPOSED = "PARENT_PROPOSED"
    TUTOR_COUNTERED = "TUTOR_COUNTERED"
    AGREED = "AGREED"
    ARBITRATION = "ARBITRATION"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_DENY = "RESOLVED_DENY"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Subject(TypedDict):
    id: str
    code: str
    display_name: str
    category: str
    requires_credential: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionPolicy(TypedDict):
    id: str
    name: str
    tier_breakpoints_cents: List[int]
    tier_rates_bps: List[int]
    trial_commission_bps: int
    trial_max_billed_minutes: int
    refund_window_hours: int
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tutor(TypedDict):
    id: str
    email: str
    full_name: str
    base_hourly_rate_cents: int
    verification_status: str
    lifetime_net_earnings_cents: int
    payout_balance_cents: int
    clawback_owed_cents: int
    reliability_score: float
    active_subject_count: int
    is_payable: bool
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict):
    id: str
    tutor_id: str
    subject_id: str
    kind: str
    document_ref: str
    status: str
    reviewed_by: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TutorSubjectTag(TypedDict):
    id: str
    tutor_id: str
    subject_id: str
    subject_rate_cents: Optional[int]
    status: str
    effective_hourly_rate_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ParentAccount(TypedDict):
    id: str
    email: str
    full_name: str
    wallet_balance_cents: int
    held_balance_cents: int
    available_balance_cents: int
    child_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    parent_account_id: str
    display_name: str
    grade_level: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    parent_account_id: str
    student_id: str
    tutor_id: str
    subject_id: str
    scheduled_start: str
    planned_minutes: int
    is_trial: bool
    quoted_rate_cents: int
    hold_amount_cents: int
    status: str
    reschedule_count: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    booking_id: str
    tutor_id: str
    actual_minutes: int
    billed_minutes: int
    settlement_status: str
    delivery_status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    session_id: str
    tutor_id: str
    gross_amount_cents: int
    commission_bps: int
    commission_cents: int
    tutor_net_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefundCase(TypedDict):
    id: str
    session_id: str
    parent_account_id: str
    tutor_id: str
    supersedes_case_id: Optional[str]
    claimed_amount_cents: int
    parent_offer_cents: int
    tutor_offer_cents: Optional[int]
    round_count: int
    granted_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
