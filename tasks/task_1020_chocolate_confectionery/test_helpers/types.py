"""Domain types: entity TypedDicts, status enums, role enum (PRD Sections 2 & 3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SALES_MANAGER = "SalesManager"
    PRODUCTION_MANAGER = "ProductionManager"
    ADMIN = "Admin"


# --- Status / enum-valued fields ---
class AccountType(str, Enum):
    RETAIL = "RETAIL"
    WHOLESALE = "WHOLESALE"
    CORPORATE = "CORPORATE"


class ProductType(str, Enum):
    SINGLE = "SINGLE"
    BUNDLE = "BUNDLE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class MoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class BatchStatus(str, Enum):
    RAW = "RAW"
    TEMPERING = "TEMPERING"
    TEMPERED = "TEMPERED"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    DISCARDED = "DISCARDED"
    EXPIRED = "EXPIRED"


class OrderType(str, Enum):
    RETAIL = "RETAIL"
    WHOLESALE = "WHOLESALE"
    PREORDER = "PREORDER"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    BACKORDERED = "BACKORDERED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class CustomOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLED = "FULFILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class MoldBookingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts ---
# Entities with the four common properties carry id/created_at/updated_at/version
# (PRD §2.4). BundleComponent is the one immutable junction that carries only
# id and created_at.


class Customer(TypedDict):
    id: str
    name: str
    email: str
    account_type: str
    credit_limit_cents: int
    loyalty_discount_pct: float
    allergen_restrictions: List[str]
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    product_type: str
    base_price_cents: int
    shelf_life_days: int
    requires_tempering: bool
    tempering_minutes: int
    unit_weight_g: float
    allergens: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BundleComponent(TypedDict):
    id: str
    bundle_product_id: str
    component_product_id: str
    quantity: int
    created_at: str


class Mold(TypedDict):
    id: str
    name: str
    cavity_count: int
    daily_capacity_units: int
    allergens: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TemperingLine(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict):
    id: str
    product_id: str
    mold_id: Optional[str]
    tempering_line_id: Optional[str]
    initial_units: int
    available_units: int
    produced_at: str
    lot_expiry: str
    temper_start: Optional[str]
    temper_end: Optional[str]
    reseed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    order_type: str
    is_gift: bool
    fulfillment_window_start: Optional[str]
    fulfillment_window_end: Optional[str]
    wallet_applied_cents: int
    subtotal_cents: int
    tax_cents: int
    gift_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    quantity: int
    unit_price_cents: float
    line_total_cents: int
    allocated_units: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    order_line_id: str
    batch_id: str
    units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    mold_id: str
    units_estimated: int
    units_produced: Optional[int]
    quote_round: int
    usage_date: Optional[str]
    quoted_amount_cents: Optional[int]
    invoiced_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class MoldBooking(TypedDict):
    id: str
    mold_id: str
    custom_order_id: str
    usage_date: str
    units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    box_product_id: str
    cadence_days: int
    next_ship_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionShipment(TypedDict):
    id: str
    subscription_id: str
    period_index: int
    scheduled_date: str
    estimated_charge_cents: int
    settled_charge_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
