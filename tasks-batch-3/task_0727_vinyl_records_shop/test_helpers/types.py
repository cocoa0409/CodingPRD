"""Domain types: entity TypedDicts, status enums, role enum for the Vinyl Records Shop API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    STORE_CLERK = "StoreClerk"
    GRADER = "Grader"
    MANAGER = "Manager"


class Format(str, Enum):
    VINYL = "VINYL"
    CD = "CD"
    CASSETTE = "CASSETTE"


class Grade(str, Enum):
    M = "M"
    NM = "NM"
    VG_PLUS = "VG_PLUS"
    VG = "VG"
    G = "G"
    F = "F"
    P = "P"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class CatalogStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    PRE_ORDER_OPEN = "PRE_ORDER_OPEN"
    PRE_ORDER_CLOSED = "PRE_ORDER_CLOSED"
    DISCONTINUED = "DISCONTINUED"


class InventoryItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_DISPLAY = "ON_DISPLAY"
    RESERVED = "RESERVED"
    SOLD = "SOLD"


class TradeInStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_INSPECTION = "UNDER_INSPECTION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    SHIPPED = "SHIPPED"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class PreOrderStatus(str, Enum):
    RESERVED = "RESERVED"
    WAITLISTED = "WAITLISTED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ConsignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    RESOLVED_REGRADE = "RESOLVED_REGRADE"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    ESCALATED = "ESCALATED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SOURCING = "SOURCING"
    ARRIVED = "ARRIVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# All entities in this API carry the common fields id/created_at/updated_at/version.

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    store_credit_cents: int
    loyalty_points: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    artist: str
    title: str
    format: str
    base_price_cents: int
    is_rsd_exclusive: bool
    catalog_status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    product_id: str
    allocation_total: int
    pickup_concurrency: int
    available_count: int
    reserved_count: int
    committed_count: int
    window_open_at: str
    window_close_at: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    product_id: str
    consignment_id: Optional[str]
    is_used: bool
    condition_grade: str
    list_price_cents: int
    status: str
    hold_start_at: Optional[str]
    hold_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    payout_method: str
    status: str
    provisional_value_cents: int
    final_value_cents: int
    created_at: str
    updated_at: str
    version: int


class TradeInLine(TypedDict):
    id: str
    trade_in_id: str
    format: str
    claimed_grade: str
    inspected_grade: Optional[str]
    base_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    channel: str
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    discount_cents: int
    shipping_cents: int
    total_cents: int
    points_earned: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    inventory_item_id: str
    qty: int
    unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class PreOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    allocation_id: str
    status: str
    pickup_window_start: str
    pickup_window_end: str
    fulfilled_item_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict):
    id: str
    consignor_id: str
    display_slot_id: Optional[str]
    list_price_cents: int
    sale_price_cents: Optional[int]
    status: str
    display_start: Optional[str]
    display_end: Optional[str]
    estimated_payout_cents: int
    actual_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class DisplaySlot(TypedDict):
    id: str
    slot_label: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class GradingDispute(TypedDict):
    id: str
    inventory_item_id: str
    customer_id: str
    claimed_grade: str
    status: str
    resolution_grade: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    product_id: Optional[str]
    description: str
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
