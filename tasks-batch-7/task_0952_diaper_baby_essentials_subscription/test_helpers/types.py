"""Domain types for the Diaper & Baby-Essentials Subscription API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Entities that the PRD declares append-only observations
(AllergenFlag, ResizeEvent, SkipRecord, PointsLedgerEntry, SubstitutionEvent)
carry only ``id`` and ``created_at`` — no ``updated_at`` and no ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    ACCOUNT_HOLDER = "AccountHolder"
    REGISTRY_OWNER = "RegistryOwner"
    GIFT_PURCHASER = "GiftPurchaser"
    SUPPORT_AGENT = "SupportAgent"
    OPS_ADMIN = "OpsAdmin"


# --------------------------------------------------------------------------
# Status / enum axes
# --------------------------------------------------------------------------
class AccountStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class Stage(str, Enum):
    NEWBORN = "NEWBORN"
    S1 = "S1"
    S2 = "S2"
    S3 = "S3"
    S4 = "S4"
    S5 = "S5"
    S6 = "S6"
    PULL_UP_2T3T = "PULL_UP_2T3T"
    PULL_UP_3T4T = "PULL_UP_3T4T"
    PULL_UP_4T5T = "PULL_UP_4T5T"


class AllergenTag(str, Enum):
    FRAGRANCE = "FRAGRANCE"
    LATEX = "LATEX"
    LOTION = "LOTION"
    DYE = "DYE"
    CHLORINE = "CHLORINE"
    ALOE = "ALOE"


class AllergenSeverity(str, Enum):
    MILD = "MILD"
    SEVERE = "SEVERE"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class SkuLine(str, Enum):
    STANDARD = "STANDARD"
    HYPOALLERGENIC = "HYPOALLERGENIC"


class SkuStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class SubscriptionLifecycleState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class SubscriptionBillingState(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    DELINQUENT = "DELINQUENT"


class CycleStatus(str, Enum):
    PLANNED = "PLANNED"
    ALLOCATED = "ALLOCATED"
    CUTOFF_LOCKED = "CUTOFF_LOCKED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    SKIPPED = "SKIPPED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class CyclePaymentStatus(str, Enum):
    UNCHARGED = "UNCHARGED"
    CHARGED = "CHARGED"
    FULLY_COVERED = "FULLY_COVERED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class CycleLineStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    SUBSTITUTION_PENDING = "SUBSTITUTION_PENDING"
    SUBSTITUTED = "SUBSTITUTED"
    SHORT_FILLED = "SHORT_FILLED"


class ResizeOrigin(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class ResizeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPLIED_CURRENT = "APPLIED_CURRENT"
    APPLIED_NEXT = "APPLIED_NEXT"
    REJECTED = "REJECTED"


class ResizeRejectReason(str, Enum):
    STAGE_PINNED = "STAGE_PINNED"


class SkipRecordStatus(str, Enum):
    APPLIED = "APPLIED"
    REVOKED = "REVOKED"


class PauseRecordStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class RegistryStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class RegistryItemStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"


class GiftOrderStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    CLAIMED_CREDIT = "CLAIMED_CREDIT"
    CLAIMED_ITEM = "CLAIMED_ITEM"
    FULFILLED = "FULFILLED"
    REFUNDED = "REFUNDED"


class ClaimMode(str, Enum):
    CREDIT = "CREDIT"
    ITEM = "ITEM"


class CreditType(str, Enum):
    GIFT = "GIFT"
    REFERRAL = "REFERRAL"
    GOODWILL = "GOODWILL"
    SHORT_FILL = "SHORT_FILL"


class CreditStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ShipmentStatus(str, Enum):
    CREATED = "CREATED"
    PICKED = "PICKED"
    IN_TRANSIT = "IN_TRANSIT"
    EXCEPTION = "EXCEPTION"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class ServiceLevel(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITED = "EXPEDITED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class PointsEntryType(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    EXPIRE = "EXPIRE"
    CLAWBACK = "CLAWBACK"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    VESTED = "VESTED"
    CLAWED_BACK = "CLAWED_BACK"
    EXPIRED = "EXPIRED"


class RefundReason(str, Enum):
    CANCEL = "CANCEL"
    RETURN = "RETURN"
    GIFT_REFUND = "GIFT_REFUND"
    GOODWILL = "GOODWILL"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class SubstitutionOutcome(str, Enum):
    SUBSTITUTED = "SUBSTITUTED"
    SHORT_FILLED = "SHORT_FILLED"


class SubstitutionReason(str, Enum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    ALLERGEN_RESCREEN = "ALLERGEN_RESCREEN"


# --------------------------------------------------------------------------
# Entities carrying the full quartet (id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class Account(TypedDict):
    id: str
    email: str
    full_name: str
    status: str
    verification_token: Optional[str]
    payment_method_on_file: bool
    referral_code: str
    referred_by_code: Optional[str]
    loyalty_account_id: str
    available_credit_cents: int
    next_charge_estimate_cents: int
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Child(TypedDict):
    id: str
    account_id: str
    name: str
    birth_date: str
    weight_grams: int
    stage: str
    stage_pinned: bool
    hypoallergenic_required: bool
    archived: bool
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    code: str
    name: str
    default_pack_count: int
    promo_discount_pct: float
    allows_hypoallergenic: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict):
    id: str
    code: str
    name: str
    stage: str
    line: str
    pack_size_units: int
    pack_price_cents: int
    allergen_tags: List[str]
    stock_packs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    account_id: str
    plan_id: str
    child_id: str
    pack_count: int
    consumption_rate_per_day: float
    cadence_override_days: Optional[int]
    cadence_interval_days: int
    anchor_date: Optional[str]
    lifecycle_state: str
    billing_state: str
    free_shipping_eligible: bool
    cumulative_pause_days: int
    auto_resize_count_in_period: int
    next_charge_cents: int
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Cycle(TypedDict):
    id: str
    subscription_id: str
    sequence_number: int
    window_start: str
    window_end: str
    ship_date: str
    cutoff_at: str
    status: str
    payment_status: str
    stage_at_allocation: Optional[str]
    subtotal_cents: int
    shipping_cents: int
    gift_credit_applied_cents: int
    referral_credit_applied_cents: int
    loyalty_redemption_applied_cents: int
    loyalty_points_redeemed: int
    promo_discount_cents: int
    total_due_cents: int
    charged_cash_cents: int
    retained_cash_cents: int
    points_earned: int
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CycleLine(TypedDict):
    id: str
    cycle_id: str
    sku_id: str
    quantity_packs: int
    unit_price_cents: int
    line_total_cents: int
    status: str
    substitution_attempts: int
    short_filled_units: int
    created_at: str
    updated_at: str
    version: int


class PauseRecord(TypedDict):
    id: str
    subscription_id: str
    start_date: str
    end_date: str
    status: str
    actual_end_date: Optional[str]
    consumed_days: int
    created_at: str
    updated_at: str
    version: int


class Registry(TypedDict):
    id: str
    owner_account_id: str
    child_id: str
    title: str
    status: str
    reopen_count: int
    completion_pct: float
    inflight_gift_count: int
    created_at: str
    updated_at: str
    version: int


class RegistryItem(TypedDict):
    id: str
    registry_id: str
    sku_id: str
    requested_quantity: int
    fulfilled_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftOrder(TypedDict):
    id: str
    registry_item_id: str
    purchaser_account_id: str
    quantity: int
    gift_message: Optional[str]
    paid_cents: int
    claim_mode: Optional[str]
    status: str
    paid_at: Optional[str]
    claimed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Credit(TypedDict):
    id: str
    account_id: str
    source_gift_order_id: Optional[str]
    source_referral_id: Optional[str]
    credit_type: str
    issued_cents: int
    consumed_cents: int
    remaining_cents: int
    forfeited_cents: int
    refundable: bool
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    account_id: str
    cycle_id: Optional[str]
    gift_order_id: Optional[str]
    status: str
    exception_count: int
    service_level: str
    eta_days: int
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict):
    id: str
    account_id: str
    points_balance: int
    tier: str
    trailing_earned_points: int
    tier_evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referrer_account_id: str
    referee_account_id: str
    vesting_cycle_id: Optional[str]
    code: str
    status: str
    credit_cents: int
    vested_at: Optional[str]
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    account_id: str
    cycle_id: Optional[str]
    gift_order_id: Optional[str]
    reason: str
    requested_cents: int
    refunded_cash_cents: int
    restock_fee_cents: int
    points_clawed_back: int
    credits_restored_cents: int
    status: str
    approved_by_user_id: Optional[str]
    settled_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Append-only observations — id + created_at only
# --------------------------------------------------------------------------
class AllergenFlag(TypedDict):
    id: str
    child_id: str
    allergen_tag: str
    severity: str
    note: Optional[str]
    created_at: str


class ResizeEvent(TypedDict):
    id: str
    subscription_id: str
    child_id: str
    target_cycle_id: Optional[str]
    origin: str
    from_stage: str
    to_stage: str
    status: str
    measured_weight_grams: Optional[int]
    reject_reason: Optional[str]
    created_at: str


class SkipRecord(TypedDict):
    id: str
    subscription_id: str
    cycle_id: str
    status: str
    anchor_before: str
    anchor_after: str
    created_at: str


class PointsLedgerEntry(TypedDict):
    id: str
    loyalty_account_id: str
    cycle_id: Optional[str]
    entry_type: str
    delta_points: int
    earn_base_cents: int
    tier_multiplier_applied: float
    expires_at: Optional[str]
    created_at: str


class SubstitutionEvent(TypedDict):
    id: str
    cycle_line_id: str
    from_sku_id: str
    to_sku_id: Optional[str]
    ladder_rung: int
    outcome: str
    price_delta_cents: int
    reason: str
    created_at: str


APPEND_ONLY_ENTITIES = (
    "AllergenFlag",
    "ResizeEvent",
    "SkipRecord",
    "PointsLedgerEntry",
    "SubstitutionEvent",
)
