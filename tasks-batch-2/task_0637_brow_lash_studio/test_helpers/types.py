"""Domain types: entity TypedDicts, status enums, role enum for the Brow & Lash Studio API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────
class StudioStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ServiceCode(str, Enum):
    FULL_SET = "FULL_SET"
    FILL = "FILL"
    LIFT = "LIFT"
    TINT = "TINT"


class ServiceCategory(str, Enum):
    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"


class MembershipTier(str, Enum):
    ESSENTIAL = "ESSENTIAL"
    PREMIER = "PREMIER"
    LUXE = "LUXE"


class LashTechStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class ConsentPatchTestStatus(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    LATE_CANCELLED = "LATE_CANCELLED"
    CANCELLED = "CANCELLED"


class RetailOrderStatus(str, Enum):
    PAID = "PAID"
    VOIDED = "VOIDED"


class RecurringScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    ENDED = "ENDED"


class SanitationLogStatus(str, Enum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class CreditLedgerReason(str, Enum):
    GRANT = "GRANT"
    ROLLOVER = "ROLLOVER"
    ROLLOVER_FORFEIT = "ROLLOVER_FORFEIT"
    CONSUME = "CONSUME"
    REFUND = "REFUND"


class UserRole(str, Enum):
    STUDIO_MANAGER = "StudioManager"
    FRONT_DESK = "FrontDesk"
    LASH_TECH = "LashTech"
    MEMBER = "Member"


# ─── Entity TypedDicts (common_fields: true carry id+created_at+updated_at+version) ───
class Studio(TypedDict):
    id: str
    name: str
    deposit_rate_pct: float
    late_cancel_cutoff_hours: int
    noshow_strike_window_days: int
    noshow_strike_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceType(TypedDict):
    id: str
    studio_id: str
    code: str
    name: str
    duration_minutes: int
    base_price_cents: int
    credit_cost: int
    category: str
    requires_patch_test: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    studio_id: str
    tier: str
    monthly_credit_allotment: int
    monthly_fee_cents: int
    rollover_cap_multiplier: float
    loyalty_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class LashTech(TypedDict):
    id: str
    studio_id: str
    full_name: str
    skill_level: int
    station_number: int
    station_sanitized_through_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    studio_id: str
    full_name: str
    email: str
    noshow_strike_count: int
    last_premium_completed_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    plan_id: str
    credit_balance: int
    cycle_anchor_utc: str
    cycles_closed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentPatchTest(TypedDict):
    id: str
    member_id: str
    administered_utc: str
    valid_through_utc: str
    consent_signed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    studio_id: str
    member_id: str
    service_type_id: str
    membership_id: Optional[str]
    lash_tech_id: str
    recurring_schedule_id: Optional[str]
    start_utc: str
    end_utc: str
    pay_with_credits: bool
    deposit_cents: int
    credits_charged: int
    deposit_forfeited_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailOrder(TypedDict):
    id: str
    member_id: str
    appointment_id: str
    lines: List[dict]
    subtotal_cents: int
    peak_surcharge_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecurringFillSchedule(TypedDict):
    id: str
    member_id: str
    service_type_id: str
    cadence_days: int
    first_start_utc: str
    next_due_utc: str
    spawned_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SanitationLog(TypedDict):
    id: str
    lash_tech_id: str
    performed_by_user_id: str
    sanitized_at_utc: str
    valid_through_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger, carries ONLY id + created_at
class CreditLedgerEntry(TypedDict):
    id: str
    membership_id: str
    delta: int
    reason: str
    source_ref_id: str
    created_at: str
