"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API are mutable audit-bearing resources, so every entity
carries id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    STORE_ASSOCIATE = "StoreAssociate"
    MERCHANDISER = "Merchandiser"
    STORE_MANAGER = "StoreManager"


# ─── Status enums ─────────────────────────────────────────────────────────
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class Category(str, Enum):
    TOPS = "TOPS"
    BOTTOMS = "BOTTOMS"
    DRESSES = "DRESSES"
    OUTERWEAR = "OUTERWEAR"
    ACCESSORIES = "ACCESSORIES"


class Season(str, Enum):
    SPRING = "SPRING"
    SUMMER = "SUMMER"
    FALL = "FALL"
    WINTER = "WINTER"


class Size(str, Enum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class SkuVariantStatus(str, Enum):
    STOCKED = "STOCKED"
    DISCONTINUED = "DISCONTINUED"


class FittingRoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


class StylistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFF = "OFF"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class MarkdownPhase(str, Enum):
    SEASONAL = "SEASONAL"
    CLEARANCE = "CLEARANCE"


class MarkdownStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    SUPERSEDED = "SUPERSEDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    SOLD = "SOLD"
    RETURNED = "RETURNED"
    EXCHANGED = "EXCHANGED"


class ReturnResolution(str, Enum):
    REFUND = "REFUND"
    EXCHANGE = "EXCHANGE"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class SpecialOrderStatus(str, Enum):
    PLACED = "PLACED"
    SOURCED = "SOURCED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class LookbookStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


# ─── Entity TypedDicts (all carry common audit fields) ────────────────────
class Boutique(TypedDict):
    id: str
    name: str
    state_code: str
    tax_rate_bps: int
    current_business_date: int
    return_window_days: int
    store_credit_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    boutique_id: str
    full_name: str
    email: str
    status: str
    store_credit_cents: int
    loyalty_points: int
    captured_spend_cents: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Style(TypedDict):
    id: str
    boutique_id: str
    style_code: str
    name: str
    category: str
    season: str
    list_price_cents: int
    current_price_cents: int
    clearance: bool
    total_available: int
    created_at: str
    updated_at: str
    version: int


class SkuVariant(TypedDict):
    id: str
    style_id: str
    size: str
    color: str
    on_hand: int
    reserved: int
    available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FittingRoom(TypedDict):
    id: str
    boutique_id: str
    label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FittingRoomHold(TypedDict):
    id: str
    fitting_room_id: str
    customer_id: str
    sku_variant_id: str
    start_minute: int
    end_minute: int
    status: str
    held_price_cents: int
    sales_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Stylist(TypedDict):
    id: str
    boutique_id: str
    full_name: str
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StylingAppointment(TypedDict):
    id: str
    stylist_id: str
    customer_id: str
    start_minute: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarkdownSchedule(TypedDict):
    id: str
    style_id: str
    phase: str
    markdown_pct: int
    effective_date: int
    status: str
    projected_price_cents: Optional[int]
    applied_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    customer_id: str
    boutique_id: str
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    loyalty_discount_cents: int
    tax_cents: int
    store_credit_applied_cents: int
    total_cents: int
    points_earned: int
    return_anchor_date: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    sales_order_id: str
    sku_variant_id: str
    qty: int
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict):
    id: str
    sales_order_id: str
    order_line_id: str
    resolution: str
    exchange_sku_variant_id: Optional[str]
    status: str
    refund_cents: int
    points_reversed: int
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    source_sku_variant_id: str
    qty: int
    ship_to_state_code: str
    status: str
    reserved_units: int
    created_at: str
    updated_at: str
    version: int


class Lookbook(TypedDict):
    id: str
    boutique_id: str
    title: str
    season: str
    style_ids: List[str]
    status: str
    featured_count: int
    created_at: str
    updated_at: str
    version: int
