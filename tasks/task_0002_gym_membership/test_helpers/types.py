"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4)."""

from enum import Enum
from typing import List, Optional, TypedDict


# ──────────────────────────────────────────────────────────
# Role enum — five roles recognized by the platform (PRD §2.1).
# ──────────────────────────────────────────────────────────

class UserRole(str, Enum):
    MEMBER = "Member"
    TRAINER = "Trainer"
    STORE_MANAGER = "StoreManager"
    BILLING_ADMIN = "BillingAdmin"
    ANY = "Any"


# ──────────────────────────────────────────────────────────
# Status enums — one per entity that has a state machine.
# ──────────────────────────────────────────────────────────

class MemberBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    GRACE = "GRACE"
    DELINQUENT = "DELINQUENT"
    REINSTATED = "REINSTATED"


class MemberAccessStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    FROZEN = "FROZEN"
    CANCELLED = "CANCELLED"


class AccountPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class MemberTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    ELITE = "ELITE"


class SubscriptionStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    GRACE = "GRACE"
    DELINQUENT = "DELINQUENT"
    CANCELLED = "CANCELLED"


class SubscriptionPlan(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    ELITE = "ELITE"


class BillingCycle(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL = "ANNUAL"


class PaymentOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    DECLINED = "DECLINED"


class BookingKind(str, Enum):
    GROUP_CLASS = "GROUP_CLASS"
    PERSONAL_TRAINING = "PERSONAL_TRAINING"


class BookingStatus(str, Enum):
    WAITLISTED = "WAITLISTED"
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class ClassSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CouponKind(str, Enum):
    PERCENT_OFF = "PERCENT_OFF"
    FIXED_OFF_CENTS = "FIXED_OFF_CENTS"
    REFERRAL_REWARD = "REFERRAL_REWARD"


class CouponApplicableTo(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    BOOKING = "BOOKING"
    BOTH = "BOTH"


class CouponStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ReferralRewardStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    PAID_OUT = "PAID_OUT"
    VOIDED = "VOIDED"


# ──────────────────────────────────────────────────────────
# TypedDicts — common-fields entities carry id/created_at/updated_at/version.
# PaymentAttempt is append-only and carries only id + created_at (PRD §2.4).
# ──────────────────────────────────────────────────────────

class Member(TypedDict, total=False):
    id: str
    email: str
    home_store_id: str
    tier: Optional[str]
    state_code: str
    billing_status: str
    access_status: str
    account_posture: str
    no_show_strike_count: int
    wallet_credit_cents: int
    suspension_window_start: Optional[str]
    suspension_window_end: Optional[str]
    referred_by_member_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    member_id: str
    plan: str
    billing_cycle: str
    base_price_cents: int
    status: str
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    auto_renew: bool
    failed_payment_attempts: int
    grace_period_end: Optional[str]
    cancellation_effective_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# PaymentAttempt is append-only per PRD §2.4 — id + created_at only,
# NO updated_at, NO version.
class PaymentAttempt(TypedDict, total=False):
    id: str
    subscription_id: str
    member_id: str
    attempt_number: int
    amount_cents: int
    gateway_txn_id: str
    idempotency_key: str
    outcome: str
    failure_reason: Optional[str]
    created_at: str


class Store(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    opens_at_local: str
    closes_at_local: str
    gate_device_id: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict, total=False):
    id: str
    store_id: str
    class_type: str
    trainer_id: str
    starts_at: str
    ends_at: str
    capacity: int
    minimum_tier: str
    equipment_pool_id: Optional[str]
    equipment_units_required: int
    reserved_seat_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trainer(TypedDict, total=False):
    id: str
    full_name: str
    home_store_id: str
    certifications: List[str]
    hourly_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class EquipmentPool(TypedDict, total=False):
    id: str
    store_id: str
    equipment_type: str
    total_units: int
    maintenance_window_start: Optional[str]
    maintenance_window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    member_id: str
    booking_kind: str
    class_session_id: Optional[str]
    trainer_id: Optional[str]
    store_id: str
    starts_at: str
    ends_at: str
    applied_coupon_id: Optional[str]
    waitlist_position: Optional[int]
    provisional_price_cents: int
    final_price_cents: Optional[int]
    status: str
    gate_check_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict, total=False):
    id: str
    code: str
    kind: str
    value: int
    applicable_to: str
    valid_from: str
    valid_until: str
    max_redemptions: int
    redemption_count: int
    status: str
    tied_to_member_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReferralReward(TypedDict, total=False):
    id: str
    sponsor_member_id: str
    invitee_member_id: str
    minted_coupon_id: Optional[str]
    status: str
    qualifying_attempt_id: Optional[str]
    reward_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
