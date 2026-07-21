"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §2.4)."""
from enum import Enum
from typing import TypedDict, List


# --- Role ---
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    MERCH_OPS = "MerchOps"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Enums (PRD §3.1–§3.9) ---
class ProductType(str, Enum):
    CANDLE = "CANDLE"
    WAX_MELT = "WAX_MELT"
    SOAP = "SOAP"
    BATH_BOMB = "BATH_BOMB"


class SkuSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class BatchStatus(str, Enum):
    CREATED = "CREATED"
    LABELED = "LABELED"
    RELEASED = "RELEASED"
    DEPLETED = "DEPLETED"
    RECALLED = "RECALLED"


class DropStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    ENDED = "ENDED"


class BundleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class OrderType(str, Enum):
    RETAIL = "RETAIL"
    BULK = "BULK"
    GIFT = "GIFT"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class OrderLineStatus(str, Enum):
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    RELEASED = "RELEASED"
    VOIDED_RECALL = "VOIDED_RECALL"
    RETURNED = "RETURNED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REFUNDED = "REFUNDED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (all entities carry id/created_at/updated_at/version per PRD §2.4) ---
class Product(TypedDict):
    id: str
    product_type: str
    collection_name: str
    scent_family: str
    title: str
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict):
    id: str
    product_id: str
    size: str
    scent: str
    list_price_cents: int
    requires_safety_label: bool
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict):
    id: str
    sku_id: str
    quantity_produced: int
    quantity_reserved: int
    quantity_shipped: int
    quantity_recalled: int
    quantity_available: int
    line_code: str
    cure_starts_at: str
    cure_ends_at: str
    is_safety_labeled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Drop(TypedDict):
    id: str
    season: str
    title: str
    starts_at: str
    ends_at: str
    listings: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bundle(TypedDict):
    id: str
    title: str
    items: List[dict]
    bundle_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    loyalty_points_balance: int
    loyalty_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    order_type: str
    gift_message: str
    recipient_name: str
    payment_status: str
    fulfillment_status: str
    total_quantity: int
    provisional_total_cents: int
    discount_cents: int
    shipping_fee_cents: int
    final_total_cents: int
    provisional_points: int
    awarded_points: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku_id: str
    batch_id: str
    quantity: int
    unit_price_cents: int
    line_subtotal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict):
    id: str
    order_id: str
    reason: str
    refund_amount_cents: int
    revoked_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    sku_id: str
    quantity: int
    cadence_days: int
    next_renewal_at: str
    renewal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
