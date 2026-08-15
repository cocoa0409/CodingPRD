"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRACTICE_MANAGER = "PracticeManager"
    COACH = "Coach"
    CLIENT = "Client"


class CredentialLevel(str, Enum):
    ACC = "ACC"
    PCC = "PCC"
    MCC = "MCC"


class CredentialStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class EthicsStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"


class TierType(str, Enum):
    SINGLE = "SINGLE"
    PACKAGE = "PACKAGE"
    MEMBERSHIP = "MEMBERSHIP"


class TierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ScopeFit(str, Enum):
    WITHIN_SCOPE = "WITHIN_SCOPE"
    OUTSIDE_SCOPE = "OUTSIDE_SCOPE"


class FitOutcome(str, Enum):
    PROCEED = "PROCEED"
    REFER_OUT = "REFER_OUT"


class LifecycleStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class PaymentStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"


class InstallmentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    LATE = "LATE"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    FORFEITED = "FORFEITED"


class GoalStatus(str, Enum):
    OPEN = "OPEN"
    ACHIEVED = "ACHIEVED"
    ABANDONED = "ABANDONED"


class CohortStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAITLISTED = "WAITLISTED"
    REMOVED = "REMOVED"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    CONSENTED = "CONSENTED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class PublishStatus(str, Enum):
    HIDDEN = "HIDDEN"
    PUBLISHED = "PUBLISHED"


class RefundBasis(str, Enum):
    COOLING_OFF = "COOLING_OFF"
    PRO_RATA = "PRO_RATA"


class RefundStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PaymentOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Coach / Client / ProgramTier / DiscoveryCall / Enrollment / Session / Goal /
# Cohort / Testimonial / RefundRequest are full resources (id, created_at,
# updated_at, version). FitAssessment / Installment / HabitCheckIn /
# CohortMembership are append-style records carrying ONLY id + created_at
# (PRD §2.4).
# ---------------------------------------------------------------------------


class Coach(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    credential_level: str
    credential_expires_on: str
    credential_status: str
    ethics_status: str
    max_concurrent_clients: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    timezone: str
    client_status: str
    engagement_score: int
    created_at: str
    updated_at: str
    version: int


class ProgramTier(TypedDict, total=False):
    id: str
    tier_code: str
    tier_type: str
    session_count: int
    price_cents: int
    duration_days: int
    installment_count_allowed: int
    reschedule_cap: int
    tier_status: str
    created_at: str
    updated_at: str
    version: int


class DiscoveryCall(TypedDict, total=False):
    id: str
    client_id: str
    coach_id: str
    scheduled_start: str
    duration_minutes: int
    call_status: str
    created_at: str
    updated_at: str
    version: int


class FitAssessment(TypedDict, total=False):
    # append-style record: id + created_at only, no updated_at/version
    id: str
    discovery_call_id: str
    scope_fit: str
    commitment_score: int
    outcome: str
    assessor_coach_id: str
    created_at: str


class Enrollment(TypedDict, total=False):
    id: str
    client_id: str
    coach_id: str
    program_tier_id: str
    discovery_call_id: str
    lifecycle_status: str
    payment_status: str
    activated_at: Optional[str]
    sessions_total: int
    sessions_total_price_basis: int
    sessions_consumed: int
    sessions_remaining: int
    late_reschedules_used: int
    pauses_used: int
    paid_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict, total=False):
    # append-style record: id + created_at only
    id: str
    enrollment_id: str
    sequence_no: int
    amount_cents: int
    due_on: Optional[str]
    installment_status: str
    created_at: str


class Session(TypedDict, total=False):
    id: str
    enrollment_id: str
    coach_id: str
    scheduled_start: str
    duration_minutes: int
    buffer_minutes: int
    session_status: str
    successor_session_id: Optional[str]
    is_late_reschedule: bool
    cohort_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict, total=False):
    id: str
    enrollment_id: str
    title: str
    target_count: int
    goal_status: str
    achieved_count: int
    created_at: str
    updated_at: str
    version: int


class HabitCheckIn(TypedDict, total=False):
    # append-style record: id + created_at only
    id: str
    goal_id: str
    check_in_date: str
    completed: bool
    created_at: str


class Cohort(TypedDict, total=False):
    id: str
    coach_id: str
    title: str
    capacity: int
    window_start: str
    window_end: str
    cohort_status: str
    created_at: str
    updated_at: str
    version: int


class CohortMembership(TypedDict, total=False):
    # append-style record: id + created_at only
    id: str
    cohort_id: str
    enrollment_id: str
    member_status: str
    joined_at: str
    created_at: str


class Testimonial(TypedDict, total=False):
    id: str
    enrollment_id: str
    outcome_rating: int
    body_text: str
    consent_status: str
    publish_status: str
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict, total=False):
    id: str
    enrollment_id: str
    requested_by_role: str
    basis: str
    amount_cents: int
    refund_status: str
    created_at: str
    updated_at: str
    version: int
