"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource definitions. Monetary amounts are integer cents.
LoyaltyLedger is an immutable audit record and carries only id + created_at (no
updated_at, no version).
"""
from enum import Enum
from typing import TypedDict, List, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SHOPPER = "Shopper"
    FULFILLMENT_AGENT = "FulfillmentAgent"
    PLATFORM_ADMIN = "PlatformAdmin"
    GUEST = "Guest"


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ProductCategory(str, Enum):
    MATERNITY = "MATERNITY"
    NURSING = "NURSING"
    POSTPARTUM = "POSTPARTUM"
    CAPSULE = "CAPSULE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class OrderType(str, Enum):
    BUY = "BUY"
    RENTAL = "RENTAL"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class RentalStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    OVERDUE = "OVERDUE"
    RETURNED = "RETURNED"
    CONVERTED_TO_BUY = "CONVERTED_TO_BUY"
    CANCELLED = "CANCELLED"
    LOST = "LOST"


class PlanTier(str, Enum):
    CAPSULE_BASIC = "CAPSULE_BASIC"
    CAPSULE_PLUS = "CAPSULE_PLUS"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class CapsuleStatus(str, Enum):
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    VOIDED = "VOIDED"


class ReturnType(str, Enum):
    REFUND = "REFUND"
    STORE_CREDIT = "STORE_CREDIT"
    EXCHANGE = "EXCHANGE"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LedgerReason(str, Enum):
    EARNED = "EARNED"
    REDEEMED = "REDEEMED"
    REVERSAL_REDEEM = "REVERSAL_REDEEM"
    CLAWBACK_EARNED = "CLAWBACK_EARNED"
    ADJUSTMENT = "ADJUSTMENT"


# --------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true carries id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Customer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    due_date: Optional[str]
    postpartum_flag: bool
    nursing_flag: bool
    loyalty_points: int
    lifetime_points: int
    loyalty_tier: str
    current_trimester: int
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    name: str
    category: str
    rentable: bool
    buy_price_cents: int
    rental_weekly_cents: int
    size_system: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductVariant(TypedDict, total=False):
    id: str
    product_id: str
    size_label: str
    trimester_fit: List[int]
    bump_room_cm: float
    inventory_on_hand: int
    rental_units_total: int
    reserved_rental_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FitProfile(TypedDict, total=False):
    id: str
    customer_id: str
    bust_cm: float
    waist_cm: float
    hip_cm: float
    pre_pregnancy_size: str
    recommended_size: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    variant_id: str
    order_type: str
    quantity: int
    rental_weeks: int
    rental_start: Optional[str]
    is_gift: bool
    subtotal_cents: int
    discount_cents: int
    redeemed_points: int
    redeemed_cents: int
    shipping_cents: int
    grand_total_cents: int
    earned_points: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class Rental(TypedDict, total=False):
    id: str
    order_id: str
    variant_id: str
    rental_start: str
    rental_end: str
    planned_weeks: int
    weekly_rate_cents: int
    deposit_cents: int
    provisional_charge_cents: int
    final_charge_cents: int
    late_fee_cents: int
    returned_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    customer_id: str
    plan_tier: str
    monthly_fee_cents: int
    items_per_capsule: int
    next_ship_date: str
    capsules_shipped: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Capsule(TypedDict, total=False):
    id: str
    subscription_id: str
    item_variant_ids: List[str]
    ship_date: str
    possession_end: str
    retail_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict, total=False):
    id: str
    order_id: str
    reason: str
    return_type: str
    refund_cents: int
    restocking_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable audit record, NO updated_at, NO version
class LoyaltyLedger(TypedDict, total=False):
    id: str
    customer_id: str
    points_delta: int
    reason: str
    balance_after: int
    related_order_id: Optional[str]
    created_at: str
