"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this domain carries id, created_at, updated_at, and version
(the PRD states there are no immutable, version-less resources).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class CustomerArStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PICKING = "PICKING"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderCreditStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    ON_HOLD = "ON_HOLD"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    SHORTED = "SHORTED"
    REMOVED = "REMOVED"


class ShipmentStatus(str, Enum):
    PICKING = "PICKING"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CREDITED = "CREDITED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class Uom(str, Enum):
    CASE = "CASE"
    SPLIT = "SPLIT"


class ReturnReason(str, Enum):
    DAMAGED = "DAMAGED"
    OVERAGE = "OVERAGE"
    QUALITY = "QUALITY"
    WRONG_ITEM = "WRONG_ITEM"


class UserRole(str, Enum):
    DISTRIBUTOR_ADMIN = "DistributorAdmin"
    SALES_REP = "SalesRep"
    WAREHOUSE_OP = "WarehouseOp"
    CREDIT_MANAGER = "CreditManager"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# All entities carry id/created_at/updated_at/version.

class Distributor(TypedDict):
    id: str
    name: str
    current_utc: str
    catalog_revision: int
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict):
    id: str
    distributor_id: str
    code: str
    name: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    distributor_id: str
    warehouse_id: str
    code: str
    delivery_dow: int
    cutoff_lead_hours: int
    min_delivery_gap_days: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    distributor_id: str
    sku: str
    name: str
    category: str
    splits_per_case: int
    split_allowed: bool
    perishable: bool
    substitute_product_id: Optional[str]
    case_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceTier(TypedDict):
    id: str
    product_id: str
    distributor_id: str
    min_cases: int
    case_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    distributor_id: str
    route_id: str
    name: str
    credit_limit_cents: int
    split_fee_cents: int
    ar_balance_cents: int
    ar_status: str
    created_at: str
    updated_at: str
    version: int


class OrderGuide(TypedDict):
    id: str
    customer_id: str
    distributor_id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class OrderGuideItem(TypedDict):
    id: str
    order_guide_id: str
    product_id: str
    par_level_splits: int
    on_hand_splits: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    product_id: str
    warehouse_id: str
    lot_code: str
    expires_on: Optional[str]
    on_hand_splits: int
    reserved_splits: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    distributor_id: str
    route_id: Optional[str]
    requested_delivery_date: str
    fulfillment_status: str
    credit_status: str
    goods_subtotal_cents: int
    split_fee_total_cents: int
    order_total_cents: int
    settled: bool
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    order_guide_item_id: Optional[str]
    uom: str
    ordered_qty: int
    fulfilled_product_id: Optional[str]
    allocated_splits: int
    substituted: bool
    short_splits: int
    unit_case_price_cents: int
    extended_price_cents: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    distributor_id: str
    warehouse_id: str
    pod_signature: Optional[str]
    delivered_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict):
    id: str
    customer_id: str
    distributor_id: str
    order_id: str
    order_line_id: str
    reason: str
    return_splits: int
    restock_fee_cents: int
    credit_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
