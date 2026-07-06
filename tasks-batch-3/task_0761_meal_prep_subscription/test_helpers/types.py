"""Domain types: entity TypedDicts, status enums, role enum for the meal-prep subscription API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CUSTOMER = "Customer"
    ANONYMOUS = "Anonymous"


class ProductionRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    AVAILABLE = "AVAILABLE"
    SOLD_OUT = "SOLD_OUT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class PauseWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class PlanChangeStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class BoxFulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class BoxBillingStatus(str, Enum):
    UNCHARGED = "UNCHARGED"
    PENDING = "PENDING"
    CHARGED = "CHARGED"
    CHARGE_FAILED = "CHARGE_FAILED"
    REFUNDED = "REFUNDED"
    WAIVED = "WAIVED"


class BoxItemStatus(str, Enum):
    SELECTED = "SELECTED"
    SWAPPED_OUT = "SWAPPED_OUT"
    REMOVED = "REMOVED"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    REWARDED = "REWARDED"
    EXPIRED = "EXPIRED"


class RefundDestination(str, Enum):
    NONE = "NONE"
    ORIGINAL_PAYMENT = "ORIGINAL_PAYMENT"
    WALLET_CREDIT = "WALLET_CREDIT"


class CreditReason(str, Enum):
    REFERRAL_REWARD = "REFERRAL_REWARD"
    SWAP_CREDIT = "SWAP_CREDIT"
    REFUND_CREDIT = "REFUND_CREDIT"
    CREDIT_APPLIED = "CREDIT_APPLIED"


# --- Entity TypedDicts (mutable entities carry id + created_at + updated_at + version) ---

class ShippingZone(TypedDict):
    id: str
    zone_code: str
    name: str
    requires_cold_pack: bool
    base_shipping_fee_cents: int
    cold_pack_fee_cents: int
    order_lead_days: int
    cutoff_time_utc: str
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    plan_code: str
    name: str
    meals_per_week: int
    price_per_meal_cents: int
    created_at: str
    updated_at: str
    version: int


class Meal(TypedDict):
    id: str
    meal_code: str
    name: str
    protein_g: int
    carb_g: int
    fat_g: int
    calories: int
    allergens: List[str]
    dietary_tags: List[str]
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    meal_id: str
    delivery_date: str
    line_code: str
    window_start: str
    window_end: str
    par_total: int
    par_reserved: int
    par_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    shipping_zone_id: str
    allergen_exclusions: List[str]
    referral_code: str
    referred_by_code: Optional[str]
    wallet_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    plan_id: str
    meals_per_week: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PauseWindow(TypedDict):
    id: str
    subscription_id: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanChange(TypedDict):
    id: str
    subscription_id: str
    from_plan_id: str
    to_plan_id: str
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Box(TypedDict):
    id: str
    subscription_id: str
    delivery_date: str
    cutoff_at: str
    plan_price_per_meal_cents: int
    meals_target: int
    base_shipping_fee_cents: int
    cold_pack_fee_snapshot_cents: int
    is_first_box: bool
    fulfillment_status: str
    billing_status: str
    subtotal_cents: int
    discount_cents: int
    shipping_fee_cents: int
    cold_pack_fee_cents: int
    credit_applied_cents: int
    total_charged_cents: int
    refund_cents: int
    refund_destination: str
    created_at: str
    updated_at: str
    version: int


class BoxItem(TypedDict):
    id: str
    box_id: str
    meal_id: str
    quantity: int
    reserved_run_id: Optional[str]
    line_gross_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    referrer_customer_id: str
    referee_customer_id: str
    code: str
    reward_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger event: carries ONLY id + created_at (no updated_at, no version).
class CreditLedger(TypedDict):
    id: str
    customer_id: str
    box_id: Optional[str]
    amount_cents: int
    reason: str
    created_at: str
