"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


# --- Role enum ---
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    STORE_STAFF = "StoreStaff"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status / enum vocabularies ---
class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class SkuCategory(str, Enum):
    CLOTHING = "CLOTHING"
    GEAR = "GEAR"
    TOY = "TOY"
    FEEDING = "FEEDING"
    NURSERY = "NURSERY"


class SizeStage(str, Enum):
    NEWBORN = "NEWBORN"
    M0_3 = "M0_3"
    M3_6 = "M3_6"
    M6_12 = "M6_12"
    M12_24 = "M12_24"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class AvailabilityStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class RegistryKind(str, Enum):
    BABY_REGISTRY = "BABY_REGISTRY"
    WISHLIST = "WISHLIST"


class RegistryStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETION_UNLOCKED = "COMPLETION_UNLOCKED"
    ARCHIVED = "ARCHIVED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    RESERVED = "RESERVED"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class PaymentMethod(str, Enum):
    STORE_CREDIT = "STORE_CREDIT"
    CARD = "CARD"


class Season(str, Enum):
    SPRING_SUMMER = "SPRING_SUMMER"
    FALL_WINTER = "FALL_WINTER"


class ItemSeason(str, Enum):
    IN_SEASON = "IN_SEASON"
    OFF_SEASON = "OFF_SEASON"


class Condition(str, Enum):
    LIKE_NEW = "LIKE_NEW"
    GOOD = "GOOD"
    FAIR = "FAIR"


class ShelfStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ConsignmentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ON_DISPLAY = "ON_DISPLAY"
    SOLD = "SOLD"


class TradeInStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    WAITLISTED = "WAITLISTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (every entity carries the common-fields tetrad) ---
class Store(TypedDict):
    id: str
    name: str
    state_code: str
    open_minute: int
    close_minute: int
    pickup_station_count: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    lifetime_spend_cents: int
    store_credit_balance_cents: int
    loyalty_points: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class SKU(TypedDict):
    id: str
    store_id: str
    sku_code: str
    name: str
    category: str
    size_stage: str
    base_price_cents: int
    on_hand_qty: int
    reserved_qty: int
    availability_status: str
    created_at: str
    updated_at: str
    version: int


class Registry(TypedDict):
    id: str
    registrant_customer_id: str
    kind: str
    title: str
    event_date: str
    status: str
    desired_value_cents: int
    fulfilled_value_cents: int
    completion_pct: float
    created_at: str
    updated_at: str
    version: int


class RegistryItem(TypedDict):
    id: str
    registry_id: str
    sku_id: str
    desired_qty: int
    fulfilled_qty: int
    created_at: str
    updated_at: str
    version: int


class RegistryGift(TypedDict):
    id: str
    registry_id: str
    registry_item_id: str
    gifter_customer_id: str
    qty: int
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    sku_id: str
    qty: int
    unit_price_cents: int
    line_total_cents: int
    fulfilled_qty: int


class Order(TypedDict):
    id: str
    customer_id: str
    store_id: str
    registry_id: Optional[str]
    lines: List[OrderLine]
    pickup_start: str
    pickup_end: str
    station_no: int
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    loyalty_discount_cents: int
    completion_discount_cents: int
    applied_discount_cents: int
    total_before_credit_cents: int
    store_credit_applied_cents: int
    amount_due_cents: int
    created_at: str
    updated_at: str
    version: int


class ConsignmentShelf(TypedDict):
    id: str
    store_id: str
    shelf_code: str
    capacity: int
    season: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentItem(TypedDict):
    id: str
    consignor_customer_id: str
    store_id: str
    shelf_id: Optional[str]
    title: str
    condition: str
    season: str
    list_price_cents: int
    display_start: Optional[str]
    display_end: Optional[str]
    payout_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    sku_id: str
    submitted_condition: str
    inspected_condition: Optional[str]
    quoted_value_cents: int
    final_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    sku_id: str
    store_id: str
    qty: int
    status: str
    created_at: str
    updated_at: str
    version: int
