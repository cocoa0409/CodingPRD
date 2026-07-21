"""Domain types: entity TypedDicts, status enums, and the role enum.

Every resource in this API carries the full common-field set (id, created_at,
updated_at, version), so every TypedDict below lists them.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Enums ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    STORE_ADMIN = "StoreAdmin"
    CUSTOMER = "Customer"
    COMMERCIAL_BUYER = "CommercialBuyer"
    CONSULTANT = "Consultant"


class ProductCategory(str, Enum):
    SYSTEM = "SYSTEM"
    LIGHTING = "LIGHTING"
    NUTRIENT = "NUTRIENT"
    CONSUMABLE = "CONSUMABLE"
    ACCESSORY = "ACCESSORY"


class InventoryLotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class CommercialAccountStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    SUSPENDED = "SUSPENDED"


class DiscountTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class OrderType(str, Enum):
    RETAIL = "RETAIL"
    COMMERCIAL = "COMMERCIAL"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ConsultantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ConsultBookingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkshopSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkshopRegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class RMAStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ─── Entity TypedDicts (all carry common fields) ──────────────────────────
class Product(TypedDict):
    id: str
    sku_code: str
    name: str
    category: str
    unit_price_cents: int
    is_hazmat: bool
    warranty_months: int
    is_subscribable: bool
    reorder_threshold: int
    unit_weight_g: int
    total_available_units: int
    reorder_flag: bool
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    product_id: str
    lot_code: str
    quantity_on_hand: int
    quantity_reserved: int
    quantity_available: int
    unit_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    wallet_credit_cents: int
    loyalty_points: int
    loyalty_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CommercialAccount(TypedDict):
    id: str
    business_name: str
    credit_limit_cents: int
    credit_used_cents: int
    payment_terms_net_days: int
    discount_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: Optional[str]
    commercial_account_id: Optional[str]
    order_type: str
    lines: List[dict]
    subtotal_cents: int
    discount_cents: int
    hazmat_surcharge_cents: int
    provisional_total_cents: int
    final_total_cents: Optional[int]
    total_cents: int
    fulfillment_status: str
    payment_status: str
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    product_id: str
    interval_days: int
    quantity_per_cycle: int
    price_locked_cents: int
    next_ship_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Consultant(TypedDict):
    id: str
    name: str
    specialty: str
    hourly_rate_cents: int
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsultBooking(TypedDict):
    id: str
    consultant_id: str
    customer_id: str
    start_at: str
    end_at: str
    design_scope: str
    estimated_fee_cents: int
    actual_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    name: str
    seat_capacity: int
    created_at: str
    updated_at: str
    version: int


class WorkshopSession(TypedDict):
    id: str
    room_id: str
    title: str
    start_at: str
    end_at: str
    capacity: int
    seats_taken: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkshopRegistration(TypedDict):
    id: str
    session_id: str
    customer_id: str
    price_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RMA(TypedDict):
    id: str
    order_id: str
    product_id: str
    return_quantity: int
    reason: str
    within_warranty: Optional[bool]
    refund_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
