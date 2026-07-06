"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    CATALOG_ADMIN = "CatalogAdmin"
    STORE_MANAGER = "StoreManager"
    STORE_ASSOCIATE = "StoreAssociate"
    CUSTOMER = "Customer"
    ANY = "Any"


# --- Status / enum dimensions ---
class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class RecallStatusDim(str, Enum):
    CLEARED = "CLEARED"
    RECALLED = "RECALLED"


class ProductCategory(str, Enum):
    BOARD_GAME = "BOARD_GAME"
    MODEL_KIT = "MODEL_KIT"
    PLUSH = "PLUSH"
    ACTION_FIGURE = "ACTION_FIGURE"
    CRAFT_KIT = "CRAFT_KIT"


class SafetyLabel(str, Enum):
    CHOKING_HAZARD = "CHOKING_HAZARD"
    SMALL_PARTS = "SMALL_PARTS"
    FLAMMABLE = "FLAMMABLE"
    BATTERY = "BATTERY"
    NONE = "NONE"


class AllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    RELEASED = "RELEASED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class OrderFulfillmentStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    READY = "READY"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class PricingVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FulfillmentType(str, Enum):
    BOPIS = "BOPIS"
    SHIP_FROM_STORE = "SHIP_FROM_STORE"


class OrderLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"
    RETURNED = "RETURNED"


class LayawayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID_IN_FULL = "PAID_IN_FULL"
    CANCELLED = "CANCELLED"


class SpecialOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CUSTOMER_REVIEW = "CUSTOMER_REVIEW"
    APPROVED = "APPROVED"
    CONVERTED = "CONVERTED"
    CANCELLED = "CANCELLED"


class RecallStatus(str, Enum):
    OPEN = "OPEN"
    ISSUED = "ISSUED"
    RESOLVED = "RESOLVED"


class RecallSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    MANDATORY = "MANDATORY"


class DemoEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GiftRegistryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class RegistryType(str, Enum):
    BIRTHDAY = "BIRTHDAY"
    HOLIDAY = "HOLIDAY"
    WISHLIST = "WISHLIST"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---
class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    age_grade_min_months: int
    safety_labels: List[str]
    msrp_cents: int
    is_exclusive: bool
    status: str
    recall_status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    name: str
    state_code: str
    event_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    product_id: str
    store_id: str
    on_hand_qty: int
    reserved_qty: int
    quarantined_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    product_id: str
    store_id: str
    allocated_qty: int
    committed_qty: int
    released_qty: int
    available_alloc_qty: int
    season_start: str
    season_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    email: str
    lifetime_points: int
    points_redeemed: int
    points_balance: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    store_id: str
    fulfillment_type: str
    fulfillment_status: str
    payment_status: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    amount_paid_cents: int
    pricing_variant: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    qty: int
    recipient_age_months: int
    unit_price_cents: int
    extended_cents: int
    line_discount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Layaway(TypedDict):
    id: str
    customer_id: str
    order_id: Optional[str]
    total_cents: int
    installment_count: int
    installment_schedule_cents: List[int]
    paid_cents: int
    remaining_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    requested_qty: int
    quoted_unit_price_cents: int
    deposit_cents: int
    quote_revision: int
    status: str
    converted_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict):
    id: str
    product_id: str
    severity: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DemoEvent(TypedDict):
    id: str
    store_id: str
    product_id: str
    start_at: str
    end_at: str
    capacity: int
    registered_customer_ids: List[str]
    registered_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftRegistry(TypedDict):
    id: str
    customer_id: str
    registry_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict):
    id: str
    order_id: str
    lines: list
    gross_refund_cents: int
    restocking_fee_cents: int
    net_refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class RegistryItem(TypedDict):
    id: str
    registry_id: str
    product_id: str
    desired_qty: int
    purchased_qty: int
    created_at: str
