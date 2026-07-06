"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    STORE_MANAGER = "StoreManager"
    PLATFORM_ADMIN = "PlatformAdmin"


class QueueStatus(str, Enum):
    OPEN = "OPEN"
    BUSY = "BUSY"
    SURGE = "SURGE"


class Channel(str, Enum):
    COUNTER = "COUNTER"
    LOCKER = "LOCKER"
    DELIVERY = "DELIVERY"


class OrderStatus(str, Enum):
    CART = "CART"
    PLACED = "PLACED"
    PREPARING = "PREPARING"
    READY = "READY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    CAPTURED = "CAPTURED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class SubscriptionStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class ChallengeStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    ROUND_COMPLETE = "ROUND_COMPLETE"
    EXPIRED = "EXPIRED"


class LoyaltyTier(str, Enum):
    GREEN = "GREEN"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class PointsReason(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    CHALLENGE_BONUS = "CHALLENGE_BONUS"
    CLAWBACK = "CLAWBACK"
    ADJUSTMENT = "ADJUSTMENT"


ALLERGEN_VOCABULARY = ["DAIRY", "GLUTEN", "NUTS", "SOY", "EGG", "SHELLFISH"]


# ── Entities with common_fields: true (carry id + created_at + updated_at + version) ──

class Store(TypedDict):
    id: str
    name: str
    state_code: str
    throughput_capacity_per_slot: int
    locker_count: int
    queue_status: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    store_id: str
    name: str
    base_price_cents: int
    base_calories: int
    allergen_tags: List[str]
    is_available: bool
    created_at: str
    updated_at: str
    version: int


class Modifier(TypedDict):
    id: str
    menu_item_id: str
    name: str
    price_delta_cents: int
    calorie_delta: int
    adds_allergen_tags: List[str]
    created_at: str
    updated_at: str
    version: int


class PickupSlot(TypedDict):
    id: str
    store_id: str
    window_start_utc: str
    window_end_utc: str
    channel: str
    reserved_count: int
    is_closed: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    home_store_id: str
    allergen_blocklist: List[str]
    wallet_credit_cents: int
    loyalty_account_id: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict):
    id: str
    customer_id: str
    points_balance: int
    lifetime_points_earned: int
    tier: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict):
    id: str
    tier_name: str
    monthly_fee_cents: int
    free_delivery: bool
    points_multiplier_bps: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    plan_id: str
    status: str
    current_period_end_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    store_id: str
    pickup_slot_id: str
    subscription_id: Optional[str]
    channel: str
    order_status: str
    settlement_status: str
    subtotal_cents: int
    delivery_fee_cents: int
    points_redeemed: int
    discount_cents: int
    wallet_applied_cents: int
    total_cents: int
    total_calories: int
    points_earned: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    menu_item_id: str
    quantity: int
    modifier_ids: List[str]
    line_total_cents: int
    line_calories: int
    effective_allergen_tags: List[str]
    created_at: str
    updated_at: str
    version: int


class LoyaltyChallenge(TypedDict):
    id: str
    customer_id: str
    target_order_count: int
    bonus_points: int
    progress_count: int
    rounds_completed: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ── Entity with common_fields: false (append-only; ONLY id + created_at) ──

class PointsLedgerEntry(TypedDict):
    id: str
    loyalty_account_id: str
    order_id: Optional[str]
    delta_points: int
    reason: str
    created_at: str
