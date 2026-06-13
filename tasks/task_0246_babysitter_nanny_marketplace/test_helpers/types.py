"""Domain types: entity TypedDicts, status enums, and the role enum.

Mirrors the resource shapes the Babysitter & Nanny Marketplace API returns.
Every entity except TaxStatement carries the full id/created_at/updated_at/version
quartet; TaxStatement is an immutable snapshot carrying only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FAMILY = "Family"
    CAREGIVER = "Caregiver"


# ─── Status / enum vocabularies ───────────────────────────────────────────
class FamilyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Tier(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class VerificationStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    CONSIDER = "CONSIDER"
    FLAGGED = "FLAGGED"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BUSY = "BUSY"
    OFFLINE = "OFFLINE"
    SUSPENDED = "SUSPENDED"


class BackgroundCheckStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_PROGRESS = "IN_PROGRESS"
    CLEAR = "CLEAR"
    CONSIDER = "CONSIDER"
    FLAGGED = "FLAGGED"
    EXPIRED = "EXPIRED"


class CareType(str, Enum):
    ONE_TIME = "ONE_TIME"
    RECURRING = "RECURRING"


class JobPostingStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    CLOSED = "CLOSED"


class InterviewKind(str, Enum):
    PHONE = "PHONE"
    VIDEO = "VIDEO"
    TRIAL = "TRIAL"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    TRIAL_BOOKED = "TRIAL_BOOKED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BackupRequestStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REVERSED = "REVERSED"


class ReviewStatus(str, Enum):
    PENDING_MODERATION = "PENDING_MODERATION"
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"


# ─── Entity TypedDicts (full quartet) ─────────────────────────────────────
class Family(TypedDict):
    id: str
    display_name: str
    email: str
    num_children: int
    required_tier: str
    wallet_balance_cents: int
    escrow_reserved_cents: int
    escrow_available_cents: int
    tax_withheld_ytd_cents: int
    cash_wages_ytd_cents: int
    is_w2_obligated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Caregiver(TypedDict):
    id: str
    full_name: str
    email: str
    hourly_rate_floor_cents: int
    background_check_tier: str
    verification_status: str
    availability_status: str
    pending_earnings_cents: int
    lifetime_paid_cents: int
    rating_avg: float
    rating_count: int
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict):
    id: str
    caregiver_id: str
    requested_tier: str
    status: str
    adjudication_note: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JobPosting(TypedDict):
    id: str
    family_id: str
    title: str
    care_type: str
    family_pay_rate_cents: int
    required_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict):
    id: str
    job_posting_id: str
    family_id: str
    caregiver_id: str
    scheduled_start: str
    scheduled_end: str
    kind: str
    status: str
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    family_id: str
    caregiver_id: str
    job_posting_id: str
    care_type: str
    agreed_rate_cents: int
    scheduled_start: str
    scheduled_end: str
    recurrence_count: int
    is_holiday: bool
    status: str
    offer_round: int
    is_last_minute: bool
    estimated_pay_cents: int
    final_pay_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BookingSession(TypedDict):
    id: str
    booking_id: str
    caregiver_id: str
    sequence_index: int
    window_start: str
    window_end: str
    status: str
    clock_in_at: Optional[str]
    clock_out_at: Optional[str]
    actual_hours: float
    gross_pay_cents: int
    is_holiday: bool
    created_at: str
    updated_at: str
    version: int


class BackupCareRequest(TypedDict):
    id: str
    family_id: str
    matched_caregiver_id: Optional[str]
    needed_start: str
    needed_end: str
    required_tier: str
    max_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    caregiver_id: str
    family_id: str
    session_ids: List[str]
    gross_pay_cents: int
    fica_withheld_cents: int
    platform_fee_cents: int
    net_pay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    booking_id: str
    family_id: str
    caregiver_id: str
    rating_value: int
    comment: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Immutable snapshot (id + created_at only) ────────────────────────────
class TaxStatement(TypedDict):
    id: str
    family_id: str
    caregiver_id: str
    tax_year: int
    cash_wages_cents: int
    fica_withheld_cents: int
    created_at: str
