"""Domain types: entity TypedDicts, status enums, and the role enum.

All names mirror the Smoothie Franchise API contract exactly.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Enums -------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FRANCHISEE = "Franchisee"
    STORE_STAFF = "StoreStaff"
    CUSTOMER = "Customer"
    ANONYMOUS = "Anonymous"


class StoreStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class IngredientUnit(str, Enum):
    GRAM = "GRAM"
    ML = "ML"
    UNIT = "UNIT"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    SPOILED = "SPOILED"


class MenuCategory(str, Enum):
    SMOOTHIE = "SMOOTHIE"
    JUICE = "JUICE"
    BOWL = "BOWL"
    WELLNESS_PACK = "WELLNESS_PACK"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class SubscriptionTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class OrderFulfillmentStatus(str, Enum):
    PLACED = "PLACED"
    PREPARING = "PREPARING"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PointsReason(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    CLAWBACK = "CLAWBACK"
    SUBSCRIPTION_BONUS = "SUBSCRIPTION_BONUS"


class CateringFulfillmentType(str, Enum):
    PICKUP = "PICKUP"
    DELIVERY = "DELIVERY"


class CateringStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReconciliationStatus(str, Enum):
    OPEN = "OPEN"
    COUNTED = "COUNTED"
    POSTED = "POSTED"


class RoyaltyBasis(str, Enum):
    NET = "NET"
    GROSS = "GROSS"


# --- Entity TypedDicts -------------------------------------------------------
# Entities below carry the common system fields id/created_at/updated_at/version,
# except PointsTransaction, which is an append-only ledger event (id + created_at).

class Franchisee(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    base_royalty_rate: float
    marketing_fee_rate: float
    lifetime_royalty_cents: int
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    franchisee_id: str
    name: str
    status: str
    catering_capacity: int
    royalty_rate_override: Optional[float]
    mtd_spoilage_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryVehicle(TypedDict):
    id: str
    store_id: str
    label: str
    headcount_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict):
    id: str
    name: str
    unit: str
    standard_cost_cents_per_unit: int
    allergen_tags: List[str]
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    store_id: str
    ingredient_id: str
    qty_received: int
    remaining_qty: int
    consumed_qty: int
    spoiled_qty: int
    unit_cost_cents: int
    received_at: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    name: str
    category: str
    base_price_cents: int
    recipe: List[dict]
    base_calories: int
    allergen_tags: List[str]
    created_at: str
    updated_at: str
    version: int


class BoostAddIn(TypedDict):
    id: str
    name: str
    price_cents: int
    calories: int
    allergen_tags: List[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    allergen_avoid: List[str]
    points_balance: int
    lifetime_points_earned: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    tier: str
    monthly_fee_cents: int
    included_smoothie_credits: int
    credits_remaining: int
    renewal_bonus_points: int
    cycle_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    store_id: str
    customer_id: str
    lines: List[dict]
    redeem_points: int
    use_subscription_credit: bool
    fulfillment_status: str
    payment_status: str
    subtotal_cents: int
    redeem_discount_cents: int
    discounted_subtotal_cents: int
    tax_cents: int
    total_cents: int
    gross_merch_cents: int
    cogs_provisional_cents: int
    cogs_final_cents: int
    credits_used: int
    points_earned: int
    total_calories: int
    allergen_summary: List[str]
    paid_at: Optional[str]
    completed_at: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PointsTransaction(TypedDict):
    # Append-only ledger event: no updated_at, no version.
    id: str
    customer_id: str
    order_id: Optional[str]
    reason: str
    delta: int
    balance_after: int
    created_at: str


class CateringBooking(TypedDict):
    id: str
    store_id: str
    customer_id: str
    delivery_vehicle_id: Optional[str]
    fulfillment_type: str
    headcount: int
    items: List[dict]
    prep_window_start: str
    prep_window_end: str
    delivery_window_start: Optional[str]
    delivery_window_end: Optional[str]
    quoted_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyReconciliation(TypedDict):
    id: str
    store_id: str
    business_date: str
    status: str
    expected_sales_cents: int
    gross_sales_cents: int
    net_sales_cents: int
    counted_cash_cents: int
    variance_cents: int
    royalty_basis: str
    royalty_rate_applied: float
    royalty_due_cents: int
    marketing_fee_cents: int
    total_franchise_due_cents: int
    created_at: str
    updated_at: str
    version: int
