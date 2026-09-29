"""Domain types for the Busking Permit Program API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD section 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PERMIT_OFFICER = "PermitOfficer"
    PERFORMER = "Performer"
    AUDITION_PANELIST = "AuditionPanelist"
    NOISE_INSPECTOR = "NoiseInspector"
    RESIDENT = "Resident"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class ActType(str, Enum):
    ACOUSTIC_MUSIC = "ACOUSTIC_MUSIC"
    AMPLIFIED_MUSIC = "AMPLIFIED_MUSIC"
    STREET_THEATRE = "STREET_THEATRE"
    VISUAL_ART = "VISUAL_ART"
    CIRCUS_SKILL = "CIRCUS_SKILL"


class PitchTier(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"


class PitchAvailabilityStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PerformerStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    BARRED = "BARRED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    AUDITION_REQUIRED = "AUDITION_REQUIRED"
    AUDITION_SCHEDULED = "AUDITION_SCHEDULED"
    AUDITION_PASSED = "AUDITION_PASSED"
    AUDITION_FAILED = "AUDITION_FAILED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DecisionOutcome(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class AuditionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PermitLifecycleStatus(str, Enum):
    PENDING_FEE = "PENDING_FEE"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PermitComplianceStatus(str, Enum):
    CLEAR = "CLEAR"
    WARNED = "WARNED"
    SUSPENDED = "SUSPENDED"


class InvoiceKind(str, Enum):
    INITIAL = "INITIAL"
    RENEWAL = "RENEWAL"


class FeeVariant(str, Enum):
    FULL_SEASON = "FULL_SEASON"
    PRORATED = "PRORATED"


class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class RefundMode(str, Enum):
    PRORATED_REFUND = "PRORATED_REFUND"
    FULL_REFUND = "FULL_REFUND"


class DrawStatus(str, Enum):
    OPEN = "OPEN"
    DRAWN = "DRAWN"
    VOID = "VOID"


class EntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WON = "WON"
    LOST = "LOST"
    FORFEITED = "FORFEITED"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    RELOCATED = "RELOCATED"
    COMPLETED = "COMPLETED"
    CANCELLED_BY_PERFORMER = "CANCELLED_BY_PERFORMER"
    CANCELLED_BY_CLOSURE = "CANCELLED_BY_CLOSURE"
    CANCELLED_BY_SUSPENSION = "CANCELLED_BY_SUSPENSION"
    CANCELLED_BY_REVOCATION = "CANCELLED_BY_REVOCATION"
    CANCELLED_BY_EXPIRY = "CANCELLED_BY_EXPIRY"


class BookingOrigin(str, Enum):
    DIRECT = "DIRECT"
    LOTTERY = "LOTTERY"


class ReadingVerdict(str, Enum):
    COMPLIANT = "COMPLIANT"
    VIOLATION = "VIOLATION"


class ComplaintCategory(str, Enum):
    NOISE = "NOISE"
    OBSTRUCTION = "OBSTRUCTION"
    CONDUCT = "CONDUCT"
    UNPERMITTED_AMPLIFICATION = "UNPERMITTED_AMPLIFICATION"


class ComplaintSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    MAJOR = "MAJOR"


class ComplaintRoute(str, Enum):
    DIRECT = "DIRECT"
    MEDIATION = "MEDIATION"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    MEDIATION = "MEDIATION"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ComplaintOutcome(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ClosureReason(str, Enum):
    SPECIAL_EVENT = "SPECIAL_EVENT"
    CONSTRUCTION = "CONSTRUCTION"
    EMERGENCY = "EMERGENCY"
    PARADE = "PARADE"


class ClosureStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class Zone(TypedDict):
    id: str
    name: str
    code: str
    base_noise_cap_db: int
    weekend_noise_bonus_db: int
    evening_start_minute: int
    evening_penalty_db: int
    quiet_hours_start_minute: int
    quiet_hours_end_minute: int
    max_concurrent_closures: int
    active_closure_count: int
    created_at: str
    updated_at: str
    version: int


class Pitch(TypedDict):
    id: str
    zone_id: str
    code: str
    tier: str
    amplification_allowed: bool
    noise_cap_db: int
    max_session_minutes: int
    daily_session_cap: int
    premium_slots_per_draw: int
    fallback_pitch_id: Optional[str]
    availability_status: str
    created_at: str
    updated_at: str
    version: int


class Performer(TypedDict):
    id: str
    legal_name: str
    stage_name: str
    email: str
    act_type: str
    conduct_score: int
    renewal_conduct_score: int
    standing: str
    upheld_complaint_count: int
    premium_wins_this_season: int
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    performer_id: str
    requested_zone_id: str
    season_year: int
    requested_act_type: str
    amplification_requested: bool
    status: str
    requires_audition: bool
    revision_count: int
    change_request_reason: Optional[str]
    reviewed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    assessed_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Audition(TypedDict):
    id: str
    application_id: str
    scheduled_for: str
    status: str
    panel_score: Optional[float]
    score_count: int
    finalized_by_user_id: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    application_id: str
    performer_id: str
    permit_number: str
    season_year: int
    next_season_year: Optional[int]
    lifecycle_status: str
    compliance_status: str
    amplification_endorsed: bool
    season_minutes_used: int
    closure_credit_minutes: int
    noise_violation_count: int
    net_fees_paid_cents: int
    activated_at: Optional[str]
    suspended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    permit_id: str
    invoice_kind: str
    fee_variant: str
    gross_fee_cents: int
    discount_cents: int
    admin_fee_cents: int
    months_covered: int
    coverage_start_month: int
    amount_due_cents: int
    amount_paid_cents: int
    refunded_cents: int
    status: str
    issued_at: str
    due_at: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotteryDraw(TypedDict):
    id: str
    pitch_id: str
    season_year: int
    slot_start_at: str
    slot_end_at: str
    entry_deadline_at: str
    winner_slots: int
    entry_count: int
    winner_count: int
    status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotteryEntry(TypedDict):
    id: str
    draw_id: str
    permit_id: str
    priority_band: Optional[int]
    rank_position: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SessionBooking(TypedDict):
    id: str
    permit_id: str
    pitch_id: str
    lottery_entry_id: Optional[str]
    relocated_from_pitch_id: Optional[str]
    start_at: str
    end_at: str
    duration_minutes: int
    amplification_planned: bool
    origin: str
    effective_noise_cap_db: int
    noise_violation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    permit_id: str
    booking_id: Optional[str]
    category: str
    description: str
    route: Optional[str]
    severity: Optional[str]
    status: str
    triaged_by_user_id: Optional[str]
    adjudicated_by_user_id: Optional[str]
    upheld_at: Optional[str]
    conduct_deduction: int
    created_at: str
    updated_at: str
    version: int


class ClosureOrder(TypedDict):
    id: str
    zone_id: str
    pitch_id: Optional[str]
    reason: str
    starts_at: str
    ends_at: str
    status: str
    affected_booking_count: int
    relocated_booking_count: int
    cancelled_booking_count: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Immutable resources — PRD section 2.4 gives these ONLY id and created_at
# ---------------------------------------------------------------------------
class AuditionScore(TypedDict):
    id: str
    audition_id: str
    panelist_user_id: str
    technical_score: int
    suitability_score: int
    safety_score: int
    composite_score: float
    created_at: str


class NoiseReading(TypedDict):
    id: str
    booking_id: str
    inspector_user_id: str
    taken_at: str
    reading_db: int
    effective_cap_db: int
    verdict: str
    created_at: str


class EpochReport(TypedDict):
    processed_at: str
    closures_lifted_count: int
    invoices_past_due_count: int
    permits_expired_count: int
    bookings_completed_count: int
    performers_rescored_count: int
