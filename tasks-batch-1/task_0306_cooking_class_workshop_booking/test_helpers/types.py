"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model. Monetary amounts are integer cents.
Two ledger-style entities (GiftCardTxn, NoShowRecord) are append-only: they
carry only `id` and `created_at` — no `updated_at`, no `version` (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ──────────────────────────────────────────────────────
class UserRole(str, Enum):
    STUDIO_ADMIN = "StudioAdmin"
    INSTRUCTOR = "Instructor"
    MEMBER = "Member"


# ─── Status enums ───────────────────────────────────────────────────
class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SkillLevel(str, Enum):
    BEGINNER = "BEGINNER"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"
    PROFESSIONAL = "PROFESSIONAL"


class MemberBookingStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    BLOCKED = "BLOCKED"


class SeriesStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FULL = "FULL"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    GROUP = "GROUP"
    PRIVATE = "PRIVATE"


class DietaryTag(str, Enum):
    NEUTRAL = "NEUTRAL"
    CONTAINS_GLUTEN = "CONTAINS_GLUTEN"
    CONTAINS_NUT = "CONTAINS_NUT"
    CONTAINS_DAIRY = "CONTAINS_DAIRY"
    ANIMAL_PRODUCT = "ANIMAL_PRODUCT"


class BookingLifecycleStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    ATTENDED = "ATTENDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class QueueStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class SubstitutionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERTED = "REVERTED"


class GiftCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    VOIDED = "VOIDED"


class GiftCardTxnKind(str, Enum):
    ISSUE = "ISSUE"
    REDEEM = "REDEEM"
    RELOAD = "RELOAD"
    REVERSAL = "REVERSAL"


class NoShowKind(str, Enum):
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"


# ─── Entity TypedDicts (common_fields: true — id/created_at/updated_at/version) ──
class Instructor(TypedDict):
    id: str
    full_name: str
    email: str
    max_skill_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    dietary_flags: List[str]
    wallet_credit_cents: int
    no_show_count: int
    late_cancel_count: int
    reliability_score: int
    booking_status: str
    created_at: str
    updated_at: str
    version: int


class RecurringSeries(TypedDict):
    id: str
    template_id: str
    instructor_id: str
    cadence: str
    occurrence_count: int
    first_start_at: str
    status: str
    active_session_count: int
    created_at: str
    updated_at: str
    version: int


class ClassTemplate(TypedDict):
    id: str
    title: str
    skill_level: str
    base_price_cents: int
    default_capacity: int
    station_fixed_cost_cents: int
    prep_minutes: int
    cleanup_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    template_id: str
    series_id: Optional[str]
    instructor_id: str
    station_id: str
    event_type: str
    start_at: str
    end_at: str
    planned_seats: int
    confirmed_seats: int
    private_event_fee_cents: int
    prep_cost_per_seat_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IngredientLine(TypedDict):
    id: str
    session_id: str
    name: str
    qty_per_seat: float
    unit_cost_cents: int
    dietary_tag: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    session_id: str
    member_id: str
    seats_requested: int
    charge_cents: int
    gift_card_applied_cents: int
    wallet_applied_cents: int
    card_applied_cents: int
    refund_cents: int
    refilled_from_waitlist: bool
    lifecycle_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    session_id: str
    member_id: str
    seats_requested: int
    queue_status: str
    promoted_booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict):
    id: str
    booking_id: str
    ingredient_line_id: str
    alternate_unit_cost_cents: int
    surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftCard(TypedDict):
    id: str
    code: str
    owner_member_id: str
    initial_value_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledger entities (common_fields: false — id + created_at only) ──
class GiftCardTxn(TypedDict):
    id: str
    gift_card_id: str
    booking_id: Optional[str]
    kind: str
    amount_cents: int
    created_at: str


class NoShowRecord(TypedDict):
    id: str
    member_id: str
    booking_id: str
    kind: str
    settlement_status: str
    created_at: str
