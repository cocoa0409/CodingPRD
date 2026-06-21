"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the Coffee Mobile Order & Loyalty PRD's resources. Mutable resources
carry id/created_at/updated_at/version; the two append-only event logs
(WalletTransaction, StarLedgerEntry) carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum vocabularies ───────────────────────────────────────────

class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class MemberTier(str, Enum):
    GREEN = "GREEN"
    GOLD = "GOLD"


class StoreStatus(str, Enum):
    OPEN = "OPEN"
    PAUSED = "PAUSED"


class MenuItemCategory(str, Enum):
    BEVERAGE = "BEVERAGE"
    FOOD = "FOOD"


class ModifierGroupCode(str, Enum):
    SIZE = "SIZE"
    MILK = "MILK"
    SHOT = "SHOT"
    SYRUP = "SYRUP"


class WalletTransactionKind(str, Enum):
    RELOAD = "RELOAD"
    AUTO_RELOAD = "AUTO_RELOAD"
    ORDER_SPEND = "ORDER_SPEND"
    REFUND = "REFUND"


class OrderFulfillmentStatus(str, Enum):
    CART = "CART"
    PLACED = "PLACED"
    IN_PREP = "IN_PREP"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class PayMethod(str, Enum):
    STORED_VALUE = "STORED_VALUE"
    EXTERNAL_CARD = "EXTERNAL_CARD"


class RewardKind(str, Enum):
    FREE_ITEM = "FREE_ITEM"
    BIRTHDAY = "BIRTHDAY"


class RewardStatus(str, Enum):
    ISSUED = "ISSUED"
    RESERVED = "RESERVED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class StarLedgerKind(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    REVERSAL = "REVERSAL"


class RefundDestination(str, Enum):
    STORED_VALUE = "STORED_VALUE"
    ORIGINAL_METHOD = "ORIGINAL_METHOD"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    STORE_OPERATOR = "StoreOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# Mutable resources carry id, created_at, updated_at, version.

class Member(TypedDict):
    id: str
    email: str
    full_name: str
    birth_month_day: str
    star_balance: int
    lifetime_stars: int
    tier: str
    last_birthday_reward_year: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    name: str
    timezone: str
    slot_capacity: int
    prep_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict):
    id: str
    store_id: str
    name: str
    base_price_cents: int
    category: str
    reward_eligible: bool
    available: bool
    created_at: str
    updated_at: str
    version: int


class ModifierOption(TypedDict):
    id: str
    menu_item_id: str
    group_code: str
    name: str
    price_delta_cents: int
    max_quantity: int
    created_at: str
    updated_at: str
    version: int


class StoredValueCard(TypedDict):
    id: str
    member_id: str
    balance_cents: int
    auto_reload_enabled: bool
    auto_reload_threshold_cents: int
    auto_reload_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    member_id: str
    store_id: str
    pickup_slot_id: str
    applied_reward_id: Optional[str]
    subtotal_cents: int
    reward_discount_cents: int
    tax_cents: int
    total_cents: int
    stars_earned: int
    fulfillment_status: str
    payment_status: str
    pay_method: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    menu_item_id: str
    quantity: int
    modifiers: list
    unit_price_cents: int
    line_total_cents: int
    is_reward_redeemed: bool
    created_at: str
    updated_at: str
    version: int


class PickupSlot(TypedDict):
    id: str
    store_id: str
    window_start: str
    window_end: str
    reserved_count: int
    created_at: str
    updated_at: str
    version: int


class RewardGrant(TypedDict):
    id: str
    member_id: str
    kind: str
    star_cost: int
    max_discount_cents: int
    expires_at: str
    status: str
    reserved_by_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    order_id: str
    amount_cents: int
    destination: str
    stars_reversed: int
    created_at: str
    updated_at: str
    version: int


# Append-only event logs: id + created_at ONLY (no updated_at, no version).

class WalletTransaction(TypedDict):
    id: str
    card_id: str
    kind: str
    amount_cents: int
    order_id: Optional[str]
    created_at: str


class StarLedgerEntry(TypedDict):
    id: str
    member_id: str
    kind: str
    delta_stars: int
    order_id: Optional[str]
    created_at: str
