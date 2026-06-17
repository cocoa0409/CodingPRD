"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource carries id, created_at, updated_at, and version.
TenderLine is the one exception: it carries only id and created_at (immutable,
append-only) — no updated_at and no version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum vocabularies ──────────────────────────────────────────────

class StorePosture(str, Enum):
    DRAWER_OPEN = "DRAWER_OPEN"
    LOCKED = "LOCKED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class PromotionKind(str, Enum):
    PERCENT_OFF = "PERCENT_OFF"
    AMOUNT_OFF = "AMOUNT_OFF"
    BOGO_50 = "BOGO_50"


class PromotionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class CashDrawerSessionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSE_REQUESTED = "CLOSE_REQUESTED"
    RECONCILED = "RECONCILED"
    FORCE_CLOSED = "FORCE_CLOSED"


class SaleKind(str, Enum):
    SALE = "SALE"
    RETURN = "RETURN"
    EXCHANGE = "EXCHANGE"


class SaleSettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    TENDERING = "TENDERING"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class SaleStockStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    RESTOCKED = "RESTOCKED"


class TenderMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    STORE_CREDIT = "STORE_CREDIT"
    GIFT_CARD = "GIFT_CARD"


class LayawayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    FULFILLED = "FULFILLED"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CountSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    DISCARDED = "DISCARDED"


class UserRole(str, Enum):
    STORE_MANAGER = "StoreManager"
    CASHIER = "Cashier"
    INVENTORY_CLERK = "InventoryClerk"
    CUSTOMER = "Customer"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ─

class Store(TypedDict):
    id: str
    name: str
    code: str
    tax_rate_bps: int
    loyalty_earn_rate_bps: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    barcode: str
    name: str
    list_price_cents: int
    tax_exempt: bool
    loyalty_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    store_id: str
    product_id: str
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    reorder_point: int
    reorder_qty: int
    below_reorder: bool
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict):
    id: str
    customer_name: str
    phone: str
    points_balance: int
    lifetime_points: int
    tier: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    code: str
    kind: str
    value: int
    min_subtotal_cents: int
    stackable: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CashDrawerSession(TypedDict):
    id: str
    store_id: str
    opening_float_cents: int
    expected_cash_cents: int
    counted_cash_cents: Optional[int]
    variance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    store_id: str
    cash_session_id: Optional[str]
    loyalty_account_id: Optional[str]
    kind: str
    original_sale_id: Optional[str]
    promo_code: Optional[str]
    redeem_points: int
    lines: list
    merchandise_subtotal_cents: int
    discount_cents: int
    loyalty_redeemed_cents: int
    tax_cents: int
    total_due_cents: int
    tendered_cents: int
    points_earned: int
    settlement_status: str
    stock_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class TenderLine(TypedDict):
    id: str
    sale_id: str
    method: str
    amount_cents: int
    change_due_cents: int
    created_at: str


class Layaway(TypedDict):
    id: str
    store_id: str
    product_id: str
    customer_id: str
    quantity: int
    total_price_cents: int
    deposit_paid_cents: int
    balance_cents: int
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Transfer(TypedDict):
    id: str
    from_store_id: str
    to_store_id: str
    product_id: str
    quantity: int
    received_qty: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CountSheet(TypedDict):
    id: str
    inventory_item_id: str
    counted_qty: int
    snapshot_on_hand_qty: int
    variance_qty: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
