"""
E-Commerce Marketplace — domain entity types and status enums.

Mirrors the scaffold's 8-entity model with Python enums for every
state-machine status and TypedDicts for payload shapes.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class ShopStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    DELISTED = "DELISTED"
    ARCHIVED = "ARCHIVED"


class PromotionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    """Order-level payment dimension."""
    UNPAID = "UNPAID"
    PAYING = "PAYING"
    PAID = "PAID"
    PARTIAL_REFUND = "PARTIAL_REFUND"
    FULL_REFUND = "FULL_REFUND"


class FulfillmentStatus(str, Enum):
    """Order-level fulfillment dimension."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class OrderStatus(str, Enum):
    """Derived composite order status."""
    CREATED = "CREATED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentRecordStatus(str, Enum):
    PENDING = "PENDING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    PROCESSED = "PROCESSED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


# ---------------------------------------------------------------------------
# Other domain enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SELLER = "Seller"
    PLATFORM_ADMIN = "PlatformAdmin"


class DiscountStrategy(str, Enum):
    PERCENTAGE_FIRST = "PERCENTAGE_FIRST"
    FIXED_FIRST = "FIXED_FIRST"


class PromoType(str, Enum):
    PERCENTAGE = "PERCENTAGE"
    FIXED_AMOUNT = "FIXED_AMOUNT"
    BUY_X_GET_Y_FREE = "BUY_X_GET_Y_FREE"


class PaymentMethod(str, Enum):
    CREDIT_CARD = "CREDIT_CARD"
    DEBIT_CARD = "DEBIT_CARD"
    WALLET = "WALLET"
    BANK_TRANSFER = "BANK_TRANSFER"


class PaymentType(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class RefundType(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Shop(TypedDict, total=False):
    id: str
    owner_id: str
    name: str
    description: Optional[str]
    status: str  # ShopStatus value
    version: int
    created_at: str
    updated_at: str


class Product(TypedDict, total=False):
    id: str
    shop_id: str
    name: str
    description: Optional[str]
    price: float
    inventory: int
    reserved: int
    status: str  # ProductStatus value
    version: int
    created_at: str
    updated_at: str


class Promotion(TypedDict, total=False):
    id: str
    shop_id: str
    name: str
    promo_type: str  # PromoType value
    discount_value: float
    buy_x: Optional[int]
    get_y_free: Optional[int]
    max_uses: Optional[int]
    current_uses: int
    budget: Optional[float]
    spent: float
    priority: int
    start_date: str
    end_date: str
    status: str  # PromotionStatus value
    version: int
    created_at: str
    updated_at: str


class OrderItem(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    product_name: str
    unit_price: float
    quantity: int
    line_total: float
    discount_amount: float
    final_amount: float


class Order(TypedDict, total=False):
    id: str
    customer_id: str
    shop_id: str
    items: List[OrderItem]
    subtotal: float
    total_discount: float
    final_total: float
    payment_status: str  # PaymentStatus value
    fulfillment_status: str  # FulfillmentStatus value
    order_status: str  # OrderStatus value (derived)
    discount_strategy: Optional[str]  # DiscountStrategy value
    reservation_expires_at: Optional[str]
    version: int
    created_at: str
    updated_at: str


class Payment(TypedDict, total=False):
    id: str
    order_id: str
    payment_type: str  # PaymentType value
    payment_method: str  # PaymentMethod value
    amount: float
    status: str  # PaymentRecordStatus value
    reference_id: Optional[str]
    created_at: str
    updated_at: str


class Refund(TypedDict, total=False):
    id: str
    order_id: str
    payment_id: str
    refund_type: str  # RefundType value
    amount: float
    reason: Optional[str]
    status: str  # RefundStatus value
    version: int
    created_at: str
    updated_at: str


class Settlement(TypedDict, total=False):
    id: str
    shop_id: str
    period_start: str
    period_end: str
    gross_amount: float
    commission_amount: float
    net_amount: float
    status: str  # SettlementStatus value
    version: int
    created_at: str
    updated_at: str
