"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    ASSOCIATE = "Associate"
    MANAGER = "Manager"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECALLED = "RECALLED"
    DISCONTINUED = "DISCONTINUED"


class WarrantyRegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECALL_FLAGGED = "RECALL_FLAGGED"
    VOID = "VOID"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RepairOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    SCHEDULED = "SCHEDULED"
    IN_REPAIR = "IN_REPAIR"
    PARTS_HOLD = "PARTS_HOLD"
    READY = "READY"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PayMode(str, Enum):
    CUSTOMER_PAY = "CUSTOMER_PAY"
    WARRANTY_COVERED = "WARRANTY_COVERED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    UNFULFILLED = "UNFULFILLED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class MonogramStatus(str, Enum):
    NONE = "NONE"
    QUEUED = "QUEUED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class TradeInStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"
    SUPERSEDED = "SUPERSEDED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SOURCED = "SOURCED"
    ARRIVED = "ARRIVED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class RecallNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class Tier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


# --------------------------------------------------------------------------
# Entity TypedDicts (full audit set: id, created_at, updated_at, version)
# --------------------------------------------------------------------------
class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    msrp_cents: int
    warranty_months: int
    length_mm: int
    width_mm: int
    height_mm: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    tier: str
    lifetime_spend_cents: int
    points_balance: int
    store_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyRegistration(TypedDict):
    id: str
    product_id: str
    customer_id: str
    serial_number: str
    purchase_date: str
    warranty_expiry: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    registration_id: str
    defect_type: str
    description: str
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    claim_id: Optional[str]
    bench_id: Optional[str]
    pay_mode: str
    quoted_total_cents: int
    warranty_cost_cents: int
    bench_start: Optional[str]
    bench_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairLine(TypedDict):
    id: str
    repair_order_id: str
    repair_type: str
    labor_hours: float
    complexity: str
    parts_cost_cents: int
    line_labor_cents: int
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    customer_id: str
    is_gift: bool
    gift_message: Optional[str]
    subtotal_cents: int
    loyalty_discount_cents: int
    tax_cents: int
    gift_wrap_fee_cents: int
    total_cents: int
    provisional_points: int
    points_credited: int
    payment_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class SalesOrderLine(TypedDict):
    id: str
    sales_order_id: str
    product_id: str
    monogram_station_id: Optional[str]
    unit_price_cents: int
    qty: int
    line_discount_pct: float
    monogram_text: Optional[str]
    monogram_fee_cents: int
    line_subtotal_cents: int
    monogram_start: Optional[str]
    monogram_end: Optional[str]
    monogram_status: str
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    product_id: str
    condition: str
    offer_amount_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    quantity: int
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecallNotice(TypedDict):
    id: str
    product_id: str
    reason: str
    remedy: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Lightweight immutable reference records: only id + created_at
# --------------------------------------------------------------------------
class Airline(TypedDict):
    id: str
    iata_code: str
    name: str
    carry_on_max_length_mm: int
    carry_on_max_width_mm: int
    carry_on_max_height_mm: int
    checked_linear_limit_mm: int
    created_at: str


class ServiceBench(TypedDict):
    id: str
    label: str
    skill: str
    created_at: str


class MonogramStation(TypedDict):
    id: str
    label: str
    method: str
    created_at: str
