"""Domain types: entity TypedDicts, status enums, role enum.

All names use the PRD's terminology for the handmade marketplace API.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SELLER = "Seller"
    BUYER = "Buyer"
    PLATFORM_ADMIN = "PlatformAdmin"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class ShopStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VACATION = "VACATION"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SOLD_OUT = "SOLD_OUT"
    REMOVED = "REMOVED"


class FulfillmentType(str, Enum):
    READY_TO_SHIP = "READY_TO_SHIP"
    MADE_TO_ORDER = "MADE_TO_ORDER"


class MaterialStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class OrderFulfillmentStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReviewStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    HIDDEN = "HIDDEN"


class CaseType(str, Enum):
    NON_DELIVERY = "NON_DELIVERY"
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    SELLER_RESPONDED = "SELLER_RESPONDED"
    ESCALATED = "ESCALATED"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_NO_REFUND = "RESOLVED_NO_REFUND"


class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_HOLD = "ON_HOLD"
    PAID = "PAID"


class VacationPeriodStatus(str, Enum):
    SCHEDULED = "SCHEDULED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
# common_fields: true  -> id + created_at + updated_at + version
class Shop(TypedDict, total=False):
    id: str
    owner_seller_id: str
    name: str
    currency: str
    status: str
    max_concurrent_production: int
    announcement: Optional[str]
    vacation_auto_reply: Optional[str]
    published_review_count: int
    simple_avg_rating: Optional[float]
    weighted_shop_rating: Optional[float]
    available_balance_cents: int
    pending_balance_cents: int
    lifetime_gross_cents: int
    lifetime_fees_cents: int
    created_at: str
    updated_at: str
    version: int


class ShippingProfile(TypedDict, total=False):
    id: str
    shop_id: str
    name: str
    origin_country: str
    base_cost_cents: int
    per_item_cost_cents: int
    free_shipping_threshold_cents: int
    processing_time_days: int
    created_at: str
    updated_at: str
    version: int


class Material(TypedDict, total=False):
    id: str
    shop_id: str
    name: str
    unit: str
    stock_qty: int
    reorder_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    shop_id: str
    shipping_profile_id: str
    primary_material_id: Optional[str]
    material_qty_per_unit: int
    title: str
    fulfillment_type: str
    processing_time_days: int
    price_cents: int
    quantity: int
    status: str
    personalization_enabled: bool
    personalization_required: bool
    personalization_char_limit: int
    variations: List[Any]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    shop_id: str
    listing_id: str
    variation_id: Optional[str]
    payout_id: Optional[str]
    buyer_id: str
    quantity: int
    personalization_note: Optional[str]
    item_subtotal_cents: int
    shipping_cents: int
    order_total_cents: int
    order_fee_cents: int
    order_net_cents: int
    refunded_cents: int
    payment_status: str
    fulfillment_status: str
    has_open_case: bool
    paid_at: Optional[str]
    ship_by_date: Optional[str]
    shipped_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict, total=False):
    id: str
    order_id: str
    listing_id: Optional[str]
    shop_id: Optional[str]
    buyer_id: str
    rating: int
    body: Optional[str]
    seller_response: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    order_id: str
    opener_buyer_id: str
    type: str
    status: str
    reason: Optional[str]
    resolution: Optional[str]
    refund_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict, total=False):
    id: str
    shop_id: str
    status: str
    order_count: int
    gross_cents: int
    fees_cents: int
    estimated_net_cents: int
    settled_net_cents: Optional[int]
    net_cents: int
    scheduled_at: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false -> append-only vacation window carries ONLY id + created_at
# (plus its own input/system fields). It has NO updated_at and NO version.
class VacationPeriod(TypedDict, total=False):
    id: str
    shop_id: str
    starts_at: str
    ends_at: str
    status: str
    message: Optional[str]
    created_at: str
