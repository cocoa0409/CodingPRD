"""Domain types: entity TypedDicts, status enums, role enum for the
Home Décor & Home-Goods Store API."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    ADMIN = "Admin"
    MERCHANDISING_MANAGER = "MerchandisingManager"
    STORE_ASSOCIATE = "StoreAssociate"
    DELIVERY_COORDINATOR = "DeliveryCoordinator"
    CUSTOMER = "Customer"


# ─── Status / enum fields ─────────────────────────────
class StoreStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESET_LOCKED = "RESET_LOCKED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ProductCategory(str, Enum):
    DECOR = "DECOR"
    FURNITURE = "FURNITURE"
    KITCHEN = "KITCHEN"
    TEXTILE = "TEXTILE"
    SEASONAL = "SEASONAL"


class MarkdownTier(str, Enum):
    FULL = "FULL"
    MARKDOWN_1 = "MARKDOWN_1"
    MARKDOWN_2 = "MARKDOWN_2"
    CLEARANCE = "CLEARANCE"


class StoreInventoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEAD = "DEAD"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class LoyaltyMemberStatus(str, Enum):
    ACTIVE = "ACTIVE"


class OrderType(str, Enum):
    CARRYOUT = "CARRYOUT"
    BOPIS = "BOPIS"
    OVERSIZED_DELIVERY = "OVERSIZED_DELIVERY"


class OrderFulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class DeliveryBookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AssemblyCrewStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ReturnVariant(str, Enum):
    RECEIPTED = "RECEIPTED"
    NON_RECEIPTED = "NON_RECEIPTED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"


class RegistryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class RegistryItemStatus(str, Enum):
    OPEN = "OPEN"
    UNAVAILABLE = "UNAVAILABLE"


class SpecialOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CUSTOMER_REVIEW = "CUSTOMER_REVIEW"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (all entities carry the common system fields) ───
class Store(TypedDict):
    id: str
    name: str
    region_code: str
    oversized_slots_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    base_price_cents: int
    clearance_floor_cents: int
    is_treasure_hunt: bool
    first_received_at: str
    status: str
    weeks_on_shelf: int
    markdown_tier: str
    current_price_cents: int
    created_at: str
    updated_at: str
    version: int


class StoreInventory(TypedDict):
    id: str
    store_id: str
    product_id: str
    allocated_qty: int
    on_hand_qty: int
    reserved_qty: int
    sold_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyMember(TypedDict):
    id: str
    email: str
    full_name: str
    lifetime_spend_cents: int
    tier: str
    points_balance: int
    points_earned_total: int
    points_redeemed_total: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    store_id: str
    member_id: Optional[str]
    order_type: str
    requested_redeem_points: int
    fulfillment_status: str
    payment_status: str
    subtotal_cents: int
    redeemed_cents: int
    total_due_cents: int
    provisional_points: int
    earned_points: int
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    qty: int
    unit_price_cents: int
    line_net_cents: int
    returned_qty: int
    created_at: str
    updated_at: str
    version: int


class DeliveryBooking(TypedDict):
    id: str
    order_id: str
    store_id: str
    crew_id: Optional[str]
    delivery_date: str
    needs_assembly: bool
    assembly_window_start: Optional[str]
    assembly_window_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AssemblyCrew(TypedDict):
    id: str
    store_id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict):
    id: str
    order_id: str
    product_id: str
    returned_qty: int
    variant: str
    status: str
    base_refund_cents: int
    restocking_fee_cents: int
    refund_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Registry(TypedDict):
    id: str
    owner_member_id: str
    title: str
    event_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistryItem(TypedDict):
    id: str
    registry_id: str
    product_id: str
    desired_qty: int
    purchased_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    store_id: str
    member_id: str
    description: str
    quoted_price_cents: Optional[int]
    quote_revision: int
    deposit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
