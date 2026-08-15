"""Domain types: entity TypedDicts, status enums, role enum.

All thirteen primary resources share the system-managed field set of
PRD section 2.4 (id, created_at, updated_at, version), so every
TypedDict below carries those four common fields.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    ACTIVITIES_DIRECTOR = "ActivitiesDirector"
    STORE_MANAGER = "StoreManager"
    LICENSING_COORDINATOR = "LicensingCoordinator"
    TREASURER = "Treasurer"
    STUDENT_CASHIER = "StudentCashier"
    CUSTOMER = "Customer"


class MerchProgramStatus(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class VendorStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class Size(str, Enum):
    XS = "XS"
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"
    XXL = "2XL"
    ONE_SIZE = "ONE_SIZE"


class SeasonalDropStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PreOrderCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    IN_PRODUCTION = "IN_PRODUCTION"
    FULFILLING = "FULFILLING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PreOrderStatus(str, Enum):
    PLACED = "PLACED"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class EventSaleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    COUNTED = "COUNTED"
    FLAGGED = "FLAGGED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class OrderChannel(str, Enum):
    EVENT_POS = "EVENT_POS"
    ONLINE = "ONLINE"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"


class PaymentStatus(str, Enum):
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class FulfillmentStatus(str, Enum):
    POS_FULFILLED = "POS_FULFILLED"
    PICKUP_PENDING = "PICKUP_PENDING"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    PICKED_UP = "PICKED_UP"
    EXPIRED_RELEASED = "EXPIRED_RELEASED"


class ExchangeStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class ExchangeCondition(str, Enum):
    RESALEABLE = "RESALEABLE"
    DAMAGED = "DAMAGED"


class AllocationRunStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ValuationMethod(str, Enum):
    FIFO = "FIFO"
    WEIGHTED_AVG = "WEIGHTED_AVG"


class MerchProgram(TypedDict, total=False):
    id: str
    name: str
    school_year: str
    status: str
    over_short_tolerance_cents: int
    exchange_window_days: int
    pickup_window_days: int
    register_buffer_minutes: int
    deposit_floor_cents: int
    valuation_method: str
    undistributed_profit_cents: int
    distributed_profit_cents: int
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    contact_email: str
    status: str
    quotes: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Design(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    artwork_ref: str
    royalty_pct: float
    licensing_fee_cents: int
    status: str
    revision_count: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductVariant(TypedDict, total=False):
    id: str
    program_id: str
    design_id: str
    drop_id: Optional[str]
    size: str
    unit_price_cents: int
    reorder_point: int
    on_hand_qty: int
    reserved_online_qty: int
    available_qty: int
    landed_unit_cost_cents: int
    low_stock: bool
    sellable: bool
    created_at: str
    updated_at: str
    version: int


class SeasonalDrop(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    opens_at: str
    closes_at: str
    status: str
    settled_margin_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    program_id: str
    variant_id: str
    vendor_id: str
    campaign_id: Optional[str]
    qty_ordered: int
    qty_received: int
    unit_cost_cents: int
    auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PreOrderCampaign(TypedDict, total=False):
    id: str
    program_id: str
    design_id: str
    unit_price_cents: int
    deposit_pct: float
    goal_units: int
    opens_at: str
    closes_at: str
    status: str
    placed_units: int
    paid_units: int
    selected_vendor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreOrder(TypedDict, total=False):
    id: str
    program_id: str
    campaign_id: str
    variant_id: str
    customer_user_id: str
    qty: int
    status: str
    deposit_due_cents: int
    balance_due_cents: int
    deposit_paid_cents: int
    balance_paid_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class EventSale(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    register_location: str
    starts_at: str
    ends_at: str
    status: str
    opening_float_cents: Optional[int]
    opened_by_user_id: Optional[str]
    cash_sales_cents: int
    card_sales_cents: int
    cash_refunds_cents: int
    closing_counted_cents: Optional[int]
    counted_by_user_id: Optional[str]
    over_short_cents: Optional[int]
    reconcile_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    program_id: str
    channel: str
    event_id: Optional[str]
    customer_user_id: str
    payment_method: str
    lines: List[Dict[str, Any]]
    total_cents: int
    margin_cents: int
    payment_status: str
    fulfillment_status: str
    refunded_cents: int
    ready_at: Optional[str]
    expires_at: Optional[str]
    picked_up_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExchangeRequest(TypedDict, total=False):
    id: str
    program_id: str
    order_id: str
    original_variant_id: str
    new_variant_id: str
    status: str
    differential_cents: int
    condition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActivityAccount(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    allocation_weight: float
    cap_cents: Optional[int]
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class AllocationRun(TypedDict, total=False):
    id: str
    program_id: str
    distributable_cents: int
    status: str
    lines: List[Dict[str, Any]]
    posted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
