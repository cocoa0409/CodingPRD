"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SHOP_STAFF = "ShopStaff"
    INVENTORY_MANAGER = "InventoryManager"
    WHOLESALE_APPROVER = "WholesaleApprover"
    PLATFORM_ADMIN = "PlatformAdmin"


class MemberType(str, Enum):
    RETAIL = "RETAIL"
    WHOLESALE = "WHOLESALE"


class ProductType(str, Enum):
    BULK_OIL = "BULK_OIL"
    BULK_VINEGAR = "BULK_VINEGAR"
    BOTTLE = "BOTTLE"
    ACCESSORY = "ACCESSORY"
    GIFT_SET = "GIFT_SET"
    BLEND = "BLEND"


class LineType(str, Enum):
    UNIT = "UNIT"
    REFILL = "REFILL"
    BUNDLE = "BUNDLE"


class FustiStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    LOW = "LOW"
    QUARANTINED = "QUARANTINED"
    EMPTY = "EMPTY"
    RETIRED = "RETIRED"


class ReplenishmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"


class WholesaleStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class WholesaleTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


# --- Entity TypedDicts (common_fields:true carry id/created_at/updated_at/version) ---

class Member(TypedDict):
    id: str
    email: str
    full_name: str
    member_type: str
    allergen_restrictions: List[str]
    wallet_credit_cents: int
    loyalty_points: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    product_type: str
    unit_price_cents: int
    price_per_ml_cents: float
    allergens: List[str]
    shelf_life_days: int
    created_at: str
    updated_at: str
    version: int


# common_fields:false — only id + created_at
class ProductComponent(TypedDict):
    id: str
    set_product_id: str
    component_product_id: str
    quantity: int
    created_at: str


class Fusti(TypedDict):
    id: str
    product_id: str
    capacity_ml: int
    current_volume_ml: int
    reserved_volume_ml: int
    available_volume_ml: int
    reorder_point_ml: int
    harvest_date: str
    best_by_date: str
    first_draw_at: Optional[str]
    status: str
    label_freshness_score: float
    sensory_freshness_score: float
    is_past_best_by: bool
    created_at: str
    updated_at: str
    version: int


class ReplenishmentOrder(TypedDict):
    id: str
    fusti_id: str
    product_id: str
    requested_volume_ml: int
    received_harvest_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WholesaleAccount(TypedDict):
    id: str
    member_id: str
    business_name: str
    tax_id: str
    status: str
    tier: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    member_id: str
    wholesale_account_id: Optional[str]
    lines: list
    payment_status: str
    fulfillment_status: str
    provisional_subtotal_cents: int
    provisional_total_cents: int
    final_subtotal_cents: Optional[int]
    final_total_cents: Optional[int]
    discount_cents: int
    shipping_fee_cents: int
    wallet_credit_applied_cents: int
    amount_charged_cents: int
    amount_refunded_cents: int
    use_wallet_credit: bool
    created_at: str
    updated_at: str
    version: int


# Reservation is a lightweight ledger row (PRD §2.4) — tests read only id/created_at + fields.
class Reservation(TypedDict):
    id: str
    order_id: str
    fusti_id: str
    volume_ml: int
    status: str
    created_at: str


class Subscription(TypedDict):
    id: str
    member_id: str
    product_id: str
    quantity: int
    volume_ml: Optional[int]
    cadence_days: int
    status: str
    next_renewal_date: str
    renewals_count: int
    last_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TastingStation(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class TastingSession(TypedDict):
    id: str
    station_id: str
    member_id: str
    start_at: str
    end_at: str
    party_size: int
    status: str
    created_at: str
    updated_at: str
    version: int
