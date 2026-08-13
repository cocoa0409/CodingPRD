"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2 and 3)."""
from enum import Enum
from typing import Optional, TypedDict


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class WarehouseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    PO_REVIEW = "PO_REVIEW"
    STOCK_RESERVED = "STOCK_RESERVED"
    CUSTOM_PRODUCTION = "CUSTOM_PRODUCTION"
    SHIPPED = "SHIPPED"
    PARTIALLY_BACKORDERED = "PARTIALLY_BACKORDERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    VOID = "VOID"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    BACKORDERED = "BACKORDERED"
    CANCELLED = "CANCELLED"


class CustomPrintJobStatus(str, Enum):
    QUEUED = "QUEUED"
    PLATING = "PLATING"
    PRINTING = "PRINTING"
    COMPLETED = "COMPLETED"
    SCRAPPED = "SCRAPPED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    RESTOCKED = "RESTOCKED"


class ReturnType(str, Enum):
    STOCK = "STOCK"
    CUSTOM = "CUSTOM"


class RestockNotificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NOTIFIED = "NOTIFIED"
    CANCELLED = "CANCELLED"


class ShipMethod(str, Enum):
    PARCEL = "PARCEL"
    FREIGHT = "FREIGHT"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PLATFORM_ADMIN = "PlatformAdmin"
    CATALOG_MANAGER = "CatalogManager"
    BUYER = "Buyer"
    ACCOUNT_APPROVER = "AccountApprover"
    WAREHOUSE_OPS = "WarehouseOps"
    CUSTOMER_SERVICE = "CustomerService"


class Account(TypedDict, total=False):
    id: str
    company_name: str
    account_type: str
    status: str
    credit_limit_cents: int
    po_required: bool
    default_warehouse_code: str
    open_receivable_cents: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    base_price_cents: int
    uom: str
    case_qty: int
    pallet_qty: int
    weight_lbs_per_unit: float
    density_pcf: float
    oversize: bool
    is_custom_print: bool
    lead_time_days: int
    ship_method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict, total=False):
    id: str
    code: str
    name: str
    zone: int
    ship_cutoff_time: str
    timezone: str
    oversize_capable: bool
    press_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inventory(TypedDict, total=False):
    id: str
    product_id: str
    warehouse_id: str
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    backorderable: bool
    reorder_point_qty: int
    created_at: str
    updated_at: str
    version: int


class QuantityBreak(TypedDict, total=False):
    # Carries only id + created_at: updated_at and version are absent (PRD section 2.4).
    id: str
    product_id: str
    min_qty: int
    unit_price_cents: int
    sort_seq: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str


class Order(TypedDict, total=False):
    id: str
    account_id: str
    status: str
    ship_zone: int
    po_number: Optional[str]
    subtotal_cents: int
    pallet_discount_cents: int
    oversize_surcharge_cents: int
    freight_estimate_cents: int
    grand_total_cents: int
    invoice_status: str
    submitted_at: Optional[str]
    promised_ship_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    qty: int
    requested_warehouse_code: Optional[str]
    print_artwork_ref: Optional[str]
    over_under_tolerance_pct: Optional[float]
    unit_price_cents: int
    freight_class: Optional[str]
    allocated_warehouse_id: Optional[str]
    status: str
    shipped_qty: int
    created_at: str
    updated_at: str
    version: int


class CustomPrintJob(TypedDict, total=False):
    id: str
    order_line_id: str
    warehouse_id: str
    status: str
    actual_qty: Optional[int]
    receive_note: Optional[str]
    started_at: Optional[str]
    occupied_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict, total=False):
    id: str
    order_id: str
    return_type: str
    status: str
    reason_code: str
    restock_fee_cents: int
    refund_cents: int
    requested_at: str
    created_at: str
    updated_at: str
    version: int


class ReturnLine(TypedDict, total=False):
    id: str
    return_id: str
    order_line_id: str
    qty: int
    created_at: str
    updated_at: str
    version: int


class RestockNotification(TypedDict, total=False):
    id: str
    account_id: str
    product_id: str
    status: str
    notified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
