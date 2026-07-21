"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this API carries the full set of common properties
(id, created_at, updated_at, version) per PRD Section 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ProductCategory(str, Enum):
    SHOE = "SHOE"
    NUTRITION = "NUTRITION"
    GEAR = "GEAR"
    APPAREL = "APPAREL"


class ProductAvailability(str, Enum):
    IN_STOCK = "IN_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class WearReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    UNDER_INSPECTION = "UNDER_INSPECTION"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class SubscriptionPlan(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    ELITE = "ELITE"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class RunningShoeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIREMENT_DUE = "RETIREMENT_DUE"
    RETIRED = "RETIRED"


class FitmentSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class TrainingBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class UserRole(str, Enum):
    MEMBER = "Member"
    FITTER = "Fitter"
    STORE_MANAGER = "StoreManager"
    ANONYMOUS = "Anonymous"


# --------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Member(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    status: str
    loyalty_points_balance: int
    tier_qualifying_spend_cents: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    mileage_life_miles: int
    stock_on_hand: int
    stock_reserved: int
    available_units: int
    availability: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    member_id: str
    promo_code: Optional[str]
    payment_status: str
    fulfillment_status: str
    subtotal_cents: int
    discount_pct_applied: float
    discount_cents: int
    price_override_discount_cents: Optional[int]
    redeemed_points: int
    redemption_cents: int
    shipping_fee_cents: int
    provisional_total_cents: int
    final_total_cents: Optional[int]
    net_paid_cents: Optional[int]
    estimated_points_earned: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    quantity: int
    unit_price_cents: int
    line_gross_cents: int
    line_points_earned: int
    is_returned: bool
    created_at: str
    updated_at: str
    version: int


class WearReturn(TypedDict):
    id: str
    order_line_id: str
    member_id: str
    reason: str
    wear_days: Optional[int]
    status: str
    inspection_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    plan: str
    status: str
    discount_pct: float
    created_at: str
    updated_at: str
    version: int


class RunningShoe(TypedDict):
    id: str
    member_id: str
    product_id: str
    source_order_id: Optional[str]
    retirement_threshold_miles: int
    total_mileage_miles: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Fitter(TypedDict):
    id: str
    full_name: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class FitmentSession(TypedDict):
    id: str
    member_id: str
    fitter_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    recommended_product_id: Optional[str]
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict):
    id: str
    title: str
    start_time: str
    end_time: str
    capacity: int
    fitter_id: Optional[str]
    booked_count: int
    available_slots: int
    created_at: str
    updated_at: str
    version: int


class TrainingBooking(TypedDict):
    id: str
    session_id: str
    member_id: str
    status: str
    waitlist_position: Optional[int]
    created_at: str
    updated_at: str
    version: int
