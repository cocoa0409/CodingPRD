"""Domain types: entity TypedDicts, status enums, role enum for the Promo Products API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CATALOG_ADMIN = "CatalogAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    PRODUCTION_MANAGER = "ProductionManager"
    CUSTOMER = "Customer"


class DecorationMethod(str, Enum):
    SCREEN_PRINT = "SCREEN_PRINT"
    EMBROIDERY = "EMBROIDERY"
    LASER_ENGRAVE = "LASER_ENGRAVE"


class StationType(str, Enum):
    SCREEN_PRESS = "SCREEN_PRESS"
    EMBROIDERY_MACHINE = "EMBROIDERY_MACHINE"
    LASER = "LASER"


class OrderType(str, Enum):
    STANDARD = "STANDARD"
    SAMPLE = "SAMPLE"
    REORDER = "REORDER"


class OrderFulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class OrderLineStatus(str, Enum):
    PENDING_ART = "PENDING_ART"
    ART_READY = "ART_READY"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    PRINTING = "PRINTING"
    QC_HOLD = "QC_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ArtProofStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts ---
# Mutable entities carry id + created_at + updated_at + version.

class Supplier(TypedDict):
    id: str
    name: str
    blank_unit_cost_cents: int
    concurrent_capacity_units: int
    reserved_blank_qty: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    supplier_id: str
    sku: str
    name: str
    min_order_qty: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    initial_credit_cents: int
    total_funded_cents: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    order_type: str
    reorder_source_order_id: Optional[str]
    in_hands_date: str
    is_rush: bool
    fulfillment_status: str
    payment_status: str
    escrow_cents: int
    deposit_required_cents: int
    art_complete: bool
    quoted_subtotal_cents: int
    quoted_rush_cents: int
    quoted_total_cents: int
    final_subtotal_cents: Optional[int]
    final_rush_cents: Optional[int]
    final_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    station_id: Optional[str]
    decoration_method: str
    quantity: int
    imprint_color_count: int
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    unit_price_cents: int
    line_setup_cents: int
    line_subtotal_cents: int
    locked_unit_price_cents: Optional[int]
    produced_qty: Optional[int]
    spoiled_qty: Optional[int]
    good_qty: Optional[int]
    final_line_subtotal_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ArtProof(TypedDict):
    id: str
    order_line_id: str
    proof_url: str
    notes: Optional[str]
    revision_number: int
    approved_version: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict):
    id: str
    order_line_id: str
    order_id: str
    product_id: str
    supplier_id: str
    ordered_blank_qty: int
    received_blank_qty: Optional[int]
    production_start: str
    production_end: str
    estimated_blank_cost_cents: Optional[int]
    actual_blank_cost_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    carrier: str
    tracking_number: Optional[str]
    shipped_at: str
    total_good_qty: int
    final_total_cents: int
    created_at: str
    updated_at: str
    version: int


# Immutable configuration entities carry ONLY id + created_at.

class PriceTier(TypedDict):
    id: str
    product_id: str
    decoration_method: str
    min_quantity: int
    unit_price_cents: int
    created_at: str


class DecorationStation(TypedDict):
    id: str
    name: str
    station_type: str
    created_at: str
