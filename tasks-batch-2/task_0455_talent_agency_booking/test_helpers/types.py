"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full common-field set
(id, created_at, updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    AGENT = "Agent"
    CASTING_DIRECTOR = "CastingDirector"
    TALENT = "Talent"


# ─── Status enums ─────────────────────────────────────
class TalentStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ROSTERED = "ROSTERED"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class UnionStatus(str, Enum):
    SAG = "SAG"
    NON_UNION = "NON_UNION"


class CastingCallStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FILLED = "FILLED"


class MediaType(str, Enum):
    BROADCAST_TV = "BROADCAST_TV"
    CABLE = "CABLE"
    STREAMING = "STREAMING"
    PRINT = "PRINT"
    DIGITAL = "DIGITAL"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AUDITION_SCHEDULED = "AUDITION_SCHEDULED"
    CALLBACK_SCHEDULED = "CALLBACK_SCHEDULED"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class SlotKind(str, Enum):
    AUDITION = "AUDITION"
    CALLBACK = "CALLBACK"


class AuditionSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class HoldKind(str, Enum):
    FIRST_REFUSAL = "FIRST_REFUSAL"
    CONFIRMED_BOOKING = "CONFIRMED_BOOKING"


class AvailabilityHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CONFLICTED = "CONFLICTED"


class DealMemoStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatusDim(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"


class CommissionEntryStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    REVERSED = "REVERSED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"


class ResidualScheduleStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"
    VOID = "VOID"


# ─── Entity TypedDicts (all carry full common-field set) ──
class Agency(TypedDict):
    id: str
    name: str
    commission_rate_bps: int
    escrow_balance_cents: int
    booked_day_count: int
    created_at: str
    updated_at: str
    version: int


class CastingDirector(TypedDict):
    id: str
    display_name: str
    studio: str
    created_at: str
    updated_at: str
    version: int


class Talent(TypedDict):
    id: str
    agency_id: str
    full_name: str
    union_status: str
    status: str
    scale_rate_cents: int
    booked_day_count: int
    created_at: str
    updated_at: str
    version: int


class CompCard(TypedDict):
    id: str
    talent_id: str
    headshot_url: str
    height_cm: int
    skills: List[str]
    is_primary: bool
    created_at: str
    updated_at: str
    version: int


class CastingCall(TypedDict):
    id: str
    casting_director_id: str
    title: str
    media_type: str
    usage_term_months: int
    shoot_start_date: str
    shoot_end_date: str
    offered_day_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict):
    id: str
    casting_call_id: str
    talent_id: str
    comp_card_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditionSlot(TypedDict):
    id: str
    submission_id: str
    casting_director_id: str
    slot_kind: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityHold(TypedDict):
    id: str
    talent_id: str
    start_date: str
    end_date: str
    hold_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DealMemo(TypedDict):
    id: str
    casting_call_id: str
    talent_id: str
    submission_id: str
    current_day_rate_cents: int
    usage_term_months: int
    round_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    deal_memo_id: str
    talent_id: str
    casting_call_id: str
    availability_hold_id: str
    start_date: str
    end_date: str
    agreed_day_rate_cents: int
    usage_term_months: int
    gross_fee_cents: int
    provisional_commission_cents: int
    final_commission_cents: Optional[int]
    booking_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class CommissionEntry(TypedDict):
    id: str
    agency_id: str
    booking_id: str
    held_cents: int
    earned_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    booking_id: str
    talent_id: str
    gross_amount_cents: int
    union_status_snapshot: str
    commission_withheld_cents: int
    net_to_talent_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ResidualSchedule(TypedDict):
    id: str
    payment_id: str
    booking_id: str
    period_index: int
    residual_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
