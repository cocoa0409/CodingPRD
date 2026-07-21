"""Domain types: entity TypedDicts, status enums, and the role enum.

All names follow the PRD's own vocabulary for the Plus-Size & Adaptive-Clothing
Retail platform (customers, catalog, orders, returns, appointments, boxes).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    FIT_SPECIALIST = "FitSpecialist"
    STORE_MANAGER = "StoreManager"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------
class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    INSIDER = "INSIDER"
    VIP = "VIP"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class BookingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SpecialistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"


class ProductCategory(str, Enum):
    TOPS = "TOPS"
    BOTTOMS = "BOTTOMS"
    DRESSES = "DRESSES"
    OUTERWEAR = "OUTERWEAR"
    INTIMATES = "INTIMATES"


class AppointmentTopic(str, Enum):
    GENERAL = "GENERAL"
    ADAPTIVE = "ADAPTIVE"
    PLUS_FORMAL = "PLUS_FORMAL"
    MATERNITY = "MATERNITY"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    PICKING = "PICKING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ReturnType(str, Enum):
    RETURN = "RETURN"
    EXCHANGE = "EXCHANGE"


class FitVerdict(str, Enum):
    RUNS_SMALL = "RUNS_SMALL"
    TRUE_TO_SIZE = "TRUE_TO_SIZE"
    RUNS_LARGE = "RUNS_LARGE"


class RefundDestination(str, Enum):
    WALLET = "WALLET"
    ORIGINAL = "ORIGINAL"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    INSPECTED = "INSPECTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class PlanTier(str, Enum):
    ESSENTIALS = "ESSENTIALS"
    SIGNATURE = "SIGNATURE"
    LUXE = "LUXE"


class Cadence(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    CURATED = "CURATED"
    SHIPPED = "SHIPPED"
    KEPT_PENDING = "KEPT_PENDING"
    SETTLED = "SETTLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Entities that can change after creation carry id/created_at/updated_at/version.
# OrderLine is an immutable snapshot: id + created_at only.
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    size_code: int
    adaptive_needs: List[str]
    loyalty_points_balance: int
    loyalty_lifetime_points: int
    loyalty_tier: str
    wallet_credit_cents: int
    no_show_count: int
    booking_status: str
    account_status: str
    created_at: str
    updated_at: str
    version: int


class FitSpecialist(TypedDict):
    id: str
    full_name: str
    specialties: List[str]
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    name: str
    category: str
    base_price_cents: int
    adaptive_features: List[str]
    size_min: int
    size_max: int
    is_special_order: bool
    restock_fee_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductVariant(TypedDict):
    id: str
    product_id: str
    size_code: int
    color: str
    price_delta_cents: int
    inventory_on_hand: int
    inventory_reserved: int
    inventory_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StylingAppointment(TypedDict):
    id: str
    customer_id: str
    specialist_id: str
    start_at: str
    end_at: str
    topic: str
    status: str
    proposed_start_at: Optional[str]
    proposed_end_at: Optional[str]
    late_cancel_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    tier_discount_cents: int
    loyalty_redeemed_points: int
    loyalty_redeemed_cents: int
    wallet_applied_cents: int
    total_cents: int
    points_earned: int
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    variant_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    created_at: str


class ReturnRequest(TypedDict):
    id: str
    order_id: str
    return_type: str
    line_ids: List[str]
    exchange_variant_id: Optional[str]
    fit_verdict: str
    refund_destination: str
    damaged_line_ids: List[str]
    status: str
    provisional_refund_cents: int
    restock_fee_cents: int
    final_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class BoxSubscription(TypedDict):
    id: str
    customer_id: str
    plan_tier: str
    cadence: str
    styling_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BoxShipment(TypedDict):
    id: str
    subscription_id: str
    items: list
    kept_variant_ids: List[str]
    status: str
    shipped_at: Optional[str]
    provisional_charge_cents: int
    final_charge_cents: int
    points_earned: int
    created_at: str
    updated_at: str
    version: int
