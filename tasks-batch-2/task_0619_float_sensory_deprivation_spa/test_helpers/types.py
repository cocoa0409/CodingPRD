"""Domain types: entity TypedDicts, status enums, role enum for the Float-Spa API."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ─────────────────────────────────────────────────────────

class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TankOperationalStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class TankSanitationStatus(str, Enum):
    CLEAN = "CLEAN"
    IN_CYCLE = "IN_CYCLE"


class TankCapacityKind(str, Enum):
    SINGLE = "SINGLE"
    DUAL = "DUAL"


class SanitationCycleStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class SanitationCycleKind(str, Enum):
    TURNOVER = "TURNOVER"
    DEEP_CLEAN = "DEEP_CLEAN"


class OrientationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RESCHEDULED = "RESCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaySource(str, Enum):
    CREDIT = "CREDIT"
    GIFT_CARD = "GIFT_CARD"
    CASH = "CASH"


class GiftCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    VOID = "VOID"


class CreditLedgerReason(str, Enum):
    GRANT = "GRANT"
    CONSUME = "CONSUME"
    FORFEIT = "FORFEIT"
    EXPIRE = "EXPIRE"


class PaymentKind(str, Enum):
    DEPOSIT_HOLD = "DEPOSIT_HOLD"
    DEPOSIT_REFUND = "DEPOSIT_REFUND"
    LATE_FEE = "LATE_FEE"
    NO_SHOW_FEE = "NO_SHOW_FEE"
    SESSION_CHARGE = "SESSION_CHARGE"
    SESSION_REFUND = "SESSION_REFUND"


class PaymentSource(str, Enum):
    GIFT_CARD = "GIFT_CARD"
    CASH = "CASH"


class UserRole(str, Enum):
    MEMBER = "Member"
    FRONT_DESK = "FrontDesk"
    ADMIN = "Admin"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Primary records carry id + created_at + updated_at + version.

class MembershipPlan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    included_floats_per_cycle: int
    rollover_cap: int
    member_discount_pct: float
    retail_float_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    status: str
    orientation_completed: bool
    waiver_signed_version: int
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    plan_id: str
    status: str
    credit_balance: int
    cycle_index: int
    cycle_start_utc: str
    cycle_end_utc: str
    monthly_fee_cents_snapshot: int
    created_at: str
    updated_at: str
    version: int


class Tank(TypedDict):
    id: str
    name: str
    capacity_kind: str
    turnover_buffer_minutes: int
    operational_status: str
    sanitation_status: str
    created_at: str
    updated_at: str
    version: int


class SanitationCycle(TypedDict):
    id: str
    tank_id: str
    booking_id: Optional[str]
    kind: str
    status: str
    started_utc: str
    ends_utc: str
    duration_minutes: int
    created_at: str
    updated_at: str
    version: int


class Attendant(TypedDict):
    id: str
    full_name: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Orientation(TypedDict):
    id: str
    member_id: str
    attendant_id: str
    start_utc: str
    end_utc: str
    status: str
    waiver_version: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    member_id: str
    tank_id: str
    membership_id: Optional[str]
    session_minutes: int
    is_couples: bool
    start_utc: str
    end_utc: str
    status: str
    pay_source: str
    gift_card_id: Optional[str]
    deposit_cents: int
    provisional_charge_cents: int
    final_charge_cents: int
    credits_consumed: int
    created_at: str
    updated_at: str
    version: int


class GiftCard(TypedDict):
    id: str
    code: str
    initial_balance_cents: int
    remaining_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledgers carry ONLY id + created_at — NO updated_at, NO version.

class CreditLedgerEntry(TypedDict):
    id: str
    membership_id: str
    booking_id: Optional[str]
    reason: str
    delta: int
    created_at: str


class Payment(TypedDict):
    id: str
    booking_id: Optional[str]
    gift_card_id: Optional[str]
    kind: str
    source: str
    amount_cents: int
    created_at: str
