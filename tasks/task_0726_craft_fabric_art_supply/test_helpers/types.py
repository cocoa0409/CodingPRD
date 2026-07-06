"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    STORE_ASSOCIATE = "StoreAssociate"
    STORE_MANAGER = "StoreManager"
    FRAMING_SPECIALIST = "FramingSpecialist"


class SellMode(str, Enum):
    UNIT = "UNIT"
    BY_YARD = "BY_YARD"
    BULK = "BULK"


class DiscountType(str, Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


class LoyaltyTier(str, Enum):
    BASIC = "BASIC"
    SILVER = "SILVER"
    GOLD = "GOLD"


class OrderFulfillmentStatus(str, Enum):
    BUILDING = "BUILDING"
    SUBMITTED = "SUBMITTED"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class OrderLineStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class WorkshopStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class FramingStatus(str, Enum):
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY = "READY"
    CANCELLED = "CANCELLED"


class ProjectBundleStatus(str, Enum):
    DRAFT = "DRAFT"
    MATERIALIZED = "MATERIALIZED"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (all entities carry id/created_at/updated_at/version) ---

class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    home_store_code: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict):
    id: str
    customer_id: str
    points_earned: int
    points_redeemed: int
    points_balance: int
    spend_ytd_cents: int
    tier_forward: str
    tier_chronological: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    sell_mode: str
    unit_price_cents: int
    min_cut_increment_yards: float
    is_clearance: bool
    special_order_only: bool
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    product_id: str
    on_hand_yards: float
    reserved_yards: float
    available_yards: float
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict):
    id: str
    code: str
    discount_type: str
    value: float
    min_basket_cents: int
    stackable: bool
    excludes_clearance: bool
    priority: int
    valid_from: str
    valid_to: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    coupon_id: Optional[str]
    project_bundle_id: Optional[str]
    fulfillment_status: str
    payment_status: str
    provisional_total_cents: int
    final_total_cents: int
    points_redeemed_on_order: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    workshop_registration_id: Optional[str]
    requested_yards: float
    actual_cut_yards: Optional[float]
    line_subtotal_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    name: str
    cleanup_buffer_min: int
    created_at: str
    updated_at: str
    version: int


class Workshop(TypedDict):
    id: str
    title: str
    status: str
    kit_product_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkshopSession(TypedDict):
    id: str
    workshop_id: str
    room_id: str
    instructor_code: str
    starts_at: str
    ends_at: str
    capacity: int
    registered_count: int
    created_at: str
    updated_at: str
    version: int


class WorkshopRegistration(TypedDict):
    id: str
    workshop_id: str
    session_id: str
    customer_id: str
    status: str
    waitlist_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FramingOrder(TypedDict):
    id: str
    order_id: str
    customer_id: str
    width_in: float
    height_in: float
    quoted_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProjectBundle(TypedDict):
    id: str
    customer_id: str
    name: str
    bom: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    quantity: float
    quoted_unit_price_cents: int
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
