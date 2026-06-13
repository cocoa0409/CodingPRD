"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Promotion Coupon Engine PRD entities and state machines.
Two record types — BlackoutWindow and ExclusionRule — are immutable configuration
and carry only id + created_at (no updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    MERCHANT_ADMIN = "MerchantAdmin"
    SHOPPER = "Shopper"
    PLATFORM_OPERATOR = "PlatformOperator"


# ------------------------------------------------------------------------- statuses
class SegmentMembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PromotionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    ARCHIVED = "ARCHIVED"


class PromoType(str, Enum):
    PERCENT_OFF = "PERCENT_OFF"
    BOGO = "BOGO"
    THRESHOLD = "THRESHOLD"


class StackingClass(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    STACKABLE = "STACKABLE"


class EligibilityMode(str, Enum):
    ALL = "ALL"
    SEGMENT = "SEGMENT"
    FIRST_ORDER = "FIRST_ORDER"


class CouponStatus(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    EXHAUSTED = "EXHAUSTED"


class UseMode(str, Enum):
    SINGLE_USE = "SINGLE_USE"
    MULTI_USE = "MULTI_USE"


class CartPricingStatus(str, Enum):
    UNPRICED = "UNPRICED"
    PRICED = "PRICED"
    STALE = "STALE"


class CartCheckoutStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CHECKED_OUT = "CHECKED_OUT"
    ABANDONED = "ABANDONED"


class CartApplicationSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_APPLY = "AUTO_APPLY"


class CartApplicationStatus(str, Enum):
    APPLIED = "APPLIED"
    REMOVED = "REMOVED"


class CouponRedemptionStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


# ------------------------------------------------------------------------- entities
# common_fields: true — id + created_at + updated_at + version
class Customer(TypedDict):
    id: str
    email: str
    display_name: str
    order_count: int
    lifetime_discount_cents: int
    created_at: str
    updated_at: str
    version: int


class Segment(TypedDict):
    id: str
    code: str
    name: str
    member_count: int
    created_at: str
    updated_at: str
    version: int


class SegmentMembership(TypedDict):
    id: str
    customer_id: str
    segment_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    name: str
    promo_type: str
    percent_off: Optional[float]
    bogo_sku: Optional[str]
    threshold_tiers: Optional[List[dict]]
    stacking_class: str
    max_stacked_discount_pct: Optional[float]
    eligibility_mode: str
    eligible_segment_id: Optional[str]
    active_from: str
    active_until: str
    budget_cap_cents: Optional[int]
    budget_consumed_cents: int
    max_redemptions_per_customer: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict):
    id: str
    promotion_id: str
    code: str
    use_mode: str
    max_total_redemptions: Optional[int]
    redeemed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Cart(TypedDict):
    id: str
    customer_id: str
    subtotal_cents: int
    total_discount_cents: int
    total_cents: int
    pricing_status: str
    checkout_status: str
    created_at: str
    updated_at: str
    version: int


class CartLine(TypedDict):
    id: str
    cart_id: str
    sku: str
    unit_price_cents: int
    quantity: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class CartApplication(TypedDict):
    id: str
    cart_id: str
    promotion_id: str
    coupon_id: Optional[str]
    source: str
    raw_discount_cents: int
    discount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CouponRedemption(TypedDict):
    id: str
    coupon_id: Optional[str]
    promotion_id: str
    customer_id: str
    cart_id: str
    discount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — id + created_at only (immutable configuration)
class BlackoutWindow(TypedDict):
    id: str
    promotion_id: str
    starts_at: str
    ends_at: str
    reason: str
    created_at: str


class ExclusionRule(TypedDict):
    id: str
    promotion_a_id: str
    promotion_b_id: str
    note: str
    created_at: str
