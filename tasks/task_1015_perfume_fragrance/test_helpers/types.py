"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the PRD's vocabulary for the Perfume & Fragrance Retail API.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    MERCHANDISER = "Merchandiser"
    FULFILLMENT_OPS = "FulfillmentOps"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Status / classification enums ────────────────────
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CustomerTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ProductKind(str, Enum):
    SINGLE = "SINGLE"
    BUNDLE = "BUNDLE"
    DISCOVERY_SET = "DISCOVERY_SET"


class Concentration(str, Enum):
    EDT = "EDT"
    EDP = "EDP"
    PARFUM = "PARFUM"
    COLOGNE = "COLOGNE"


class NoteFamily(str, Enum):
    CITRUS = "CITRUS"
    FLORAL = "FLORAL"
    WOODY = "WOODY"
    ORIENTAL = "ORIENTAL"
    FOUGERE = "FOUGERE"
    GOURMAND = "GOURMAND"


class NoteLevel(str, Enum):
    TOP = "TOP"
    HEART = "HEART"
    BASE = "BASE"


class VariantKind(str, Enum):
    FULL_BOTTLE = "FULL_BOTTLE"
    DECANT = "DECANT"
    SAMPLE = "SAMPLE"


class VariantStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class OrderFulfillmentStatus(str, Enum):
    CART = "CART"
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    PARTIALLY_RETURNED = "PARTIALLY_RETURNED"
    RETURNED = "RETURNED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class SubscriptionTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"


class AllocationWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReturnCondition(str, Enum):
    SEALED = "SEALED"
    OPENED = "OPENED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class LoyaltyReason(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"


class LoyaltySourceType(str, Enum):
    ORDER = "ORDER"
    RETURN = "RETURN"


# ─── Entity TypedDicts ────────────────────────────────
# Entities carrying the full common-field set (id, created_at, updated_at, version).
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    status: str
    loyalty_points_balance: int
    lifetime_spend_cents: int
    tier: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    name: str
    brand: str
    kind: str
    concentration: str
    notes: list
    is_exclusive: bool
    per_customer_limit: Optional[int]
    component_variant_ids: list
    hygiene_returnable: bool
    created_at: str
    updated_at: str
    version: int


class Variant(TypedDict):
    id: str
    product_id: str
    kind: str
    volume_ml: float
    unit_price_cents: int
    on_hand_qty: int
    reserved_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    fulfillment_status: str
    payment_status: str
    subtotal_cents: int
    discount_cents: int
    loyalty_redeemed_cents: int
    shipping_fee_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    variant_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    points_earned: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    tier: str
    monthly_fee_cents: int
    pending_fee_cents: Optional[int]
    fee_effective_date: Optional[str]
    included_sample_credits: int
    status: str
    current_period_end: str
    projected_next_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    subscription_id: str
    period_start: str
    period_end: str
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationWindow(TypedDict):
    id: str
    product_id: str
    window_start: str
    window_end: str
    total_allocation: int
    per_customer_cap: int
    claimed_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict):
    id: str
    order_id: str
    line_ids: list
    condition: str
    refund_estimate_cents: int
    final_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only records — carry ONLY id + created_at (no updated_at, no version).
class AllocationClaim(TypedDict):
    id: str
    window_id: str
    customer_id: str
    units: int
    created_at: str


class LoyaltyTransaction(TypedDict):
    id: str
    customer_id: str
    points_delta: int
    reason: str
    source_type: str
    source_id: str
    created_at: str
