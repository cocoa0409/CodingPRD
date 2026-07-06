"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    BAKE_MANAGER = "BakeManager"
    CASHIER = "Cashier"
    ROUTE_DRIVER = "RouteDriver"
    WHOLESALE_CLIENT = "WholesaleClient"


class ProductCategory(str, Enum):
    DONUT = "DONUT"
    BAGEL = "BAGEL"


class ProductionDayStatus(str, Enum):
    OPEN = "OPEN"
    BAKING = "BAKING"
    SELLING = "SELLING"
    CUTOFF = "CUTOFF"
    RECONCILED = "RECONCILED"


class BakeBatchStatus(str, Enum):
    PLANNED = "PLANNED"
    BAKED = "BAKED"
    MARKED_DOWN = "MARKED_DOWN"
    SWEPT = "SWEPT"


class RetailOrderStatus(str, Enum):
    CART = "CART"
    PAID = "PAID"
    VOIDED = "VOIDED"
    REFUNDED = "REFUNDED"


class WholesaleAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class StandingOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class WholesaleDeliveryStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PICKED = "PICKED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class PreOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


# All entities carry the full common fields (id, created_at, updated_at, version).

class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    dozen_price_cents: int
    bulk_threshold: int
    bulk_unit_price_cents: int
    unit_cost_cents: int
    allergens: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class ProductionDay(TypedDict):
    id: str
    business_date: str
    delivery_cutoff_utc: str
    status: str
    gross_sales_cents: int
    markdown_loss_cents: int
    waste_cost_cents: int
    expected_full_value_cents: int
    reconciliation_variance_cents: int
    created_at: str
    updated_at: str
    version: int


class BakeBatch(TypedDict):
    id: str
    production_day_id: str
    product_id: str
    par_qty: int
    baked_qty: int
    sold_qty: int
    markdown_sold_qty: int
    remaining_qty: int
    wasted_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailOrder(TypedDict):
    id: str
    production_day_id: str
    loyalty_account_id: Optional[str]
    line_items: list
    subtotal_cents: int
    loyalty_discount_cents: int
    total_cents: int
    redeem_reward: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict):
    id: str
    phone: str
    name: str
    punch_count: int
    reward_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class WholesaleAccount(TypedDict):
    id: str
    name: str
    discount_pct: float
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingOrder(TypedDict):
    id: str
    wholesale_account_id: str
    delivery_dow: int
    line_items: list
    status: str
    created_at: str
    updated_at: str
    version: int


class WholesaleDelivery(TypedDict):
    id: str
    production_day_id: str
    standing_order_id: str
    wholesale_account_id: str
    route_window_start: str
    route_window_end: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PreOrder(TypedDict):
    id: str
    wholesale_account_id: str
    pickup_production_day_id: str
    pickup_window_start: str
    pickup_window_end: str
    line_items: list
    subtotal_cents: int
    deposit_due_cents: int
    deposit_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
