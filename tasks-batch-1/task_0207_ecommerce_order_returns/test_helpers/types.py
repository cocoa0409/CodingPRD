"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the PRD exactly. Entities that carry the full common-field
set (id, created_at, updated_at, version) are distinguished from CreditLedgerEntry,
which is an immutable audit record carrying only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    CUSTOMER = "Customer"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    STORE_ADMIN = "StoreAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class OrderPaymentStatus(str, Enum):
    CART = "CART"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class OrderFulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    SHIPPED = "SHIPPED"
    PARTIALLY_DELIVERED = "PARTIALLY_DELIVERED"
    DELIVERED = "DELIVERED"
    BACKORDERED = "BACKORDERED"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class ShipmentStatus(str, Enum):
    PENDING = "PENDING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REFUNDED = "REFUNDED"
    EXCHANGED = "EXCHANGED"
    RESTOCKED = "RESTOCKED"
    CANCELLED = "CANCELLED"


class ReturnReason(str, Enum):
    DEFECTIVE = "DEFECTIVE"
    WRONG_ITEM = "WRONG_ITEM"
    NO_LONGER_WANTED = "NO_LONGER_WANTED"
    ARRIVED_LATE = "ARRIVED_LATE"


class ReturnResolution(str, Enum):
    REFUND = "REFUND"
    STORE_CREDIT = "STORE_CREDIT"
    EXCHANGE = "EXCHANGE"


class RefundDestination(str, Enum):
    ORIGINAL_PAYMENT = "ORIGINAL_PAYMENT"
    STORE_CREDIT = "STORE_CREDIT"


class RefundStatus(str, Enum):
    SETTLED = "SETTLED"


class CreditLedgerKind(str, Enum):
    REFUND_CREDIT = "REFUND_CREDIT"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"
    REDEMPTION = "REDEMPTION"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true → id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    store_credit_cents: int
    lifetime_purchased_cents: int
    lifetime_refunded_cents: int
    return_risk_score: float
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict):
    id: str
    code: str
    name: str
    fulfillment_priority: int
    accepts_returns: bool
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    title: str
    unit_price_cents: int
    tax_rate_bps: int
    restocking_fee_bps: int
    return_window_days: int
    final_sale: bool
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    product_id: str
    warehouse_id: str
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    payment_status: str
    fulfillment_status: str
    promo_flat_cents: int
    subtotal_cents: int
    discounted_subtotal_cents: int
    tax_total_cents: int
    shipping_fee_cents: int
    grand_total_cents: int
    captured_total_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    qty: int
    unit_price_cents_snapshot: int
    tax_rate_bps_snapshot: int
    line_tax_cents: int
    reserved_qty: int
    backordered_qty: int
    shipped_qty: int
    returned_qty: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    order_line_id: str
    warehouse_id: str
    product_id: str
    qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    warehouse_id: str
    status: str
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShipmentLine(TypedDict):
    id: str
    shipment_id: str
    reservation_id: str
    order_line_id: str
    qty: int
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict):
    id: str
    order_id: str
    customer_id: str
    status: str
    reason: str
    resolution: str
    refund_subtotal_cents: int
    restocking_fee_cents: int
    settlement_cents: int
    created_at: str
    updated_at: str
    version: int


class ReturnLine(TypedDict):
    id: str
    return_authorization_id: str
    order_line_id: str
    return_qty: int
    exchange_product_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    return_authorization_id: str
    order_id: str
    customer_id: str
    destination: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable audit record: id + created_at only.
class CreditLedgerEntry(TypedDict):
    id: str
    customer_id: str
    refund_id: Optional[str]
    amount_cents: int
    kind: str
    created_at: str
