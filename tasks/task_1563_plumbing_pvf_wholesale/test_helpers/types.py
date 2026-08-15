"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    BRANCH_MANAGER = "BranchManager"
    COUNTER_REP = "CounterRep"
    INSIDE_SALES = "InsideSales"
    WAREHOUSE_LEAD = "WarehouseLead"
    CONTRACTOR = "Contractor"


class ProductCategory(str, Enum):
    PIPE = "PIPE"
    VALVE = "VALVE"
    FITTING = "FITTING"
    FIXTURE = "FIXTURE"


class PricingTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class AccountTerms(str, Enum):
    COD = "COD"
    NET_15 = "NET_15"
    NET_30 = "NET_30"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    SUSPENDED = "SUSPENDED"


class ProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    REVISED = "REVISED"
    LOST = "LOST"
    EXPIRED = "EXPIRED"
    CONVERTED = "CONVERTED"


class SheetStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    APPROVED = "APPROVED"
    REVISED = "REVISED"
    ORDERED = "ORDERED"


class PaymentStatus(str, Enum):
    UNINVOICED = "UNINVOICED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class FulfillmentStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PICKING = "PICKING"
    STAGED = "STAGED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class OrderSource(str, Enum):
    COUNTER = "COUNTER"
    PROJECT = "PROJECT"
    SHOWROOM = "SHOWROOM"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class SubstituteStatus(str, Enum):
    NONE = "NONE"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PriceSource(str, Enum):
    COUNTER_TIER = "COUNTER_TIER"
    PROMO = "PROMO"
    MANUAL_OVERRIDE = "MANUAL_OVERRIDE"
    QUOTE_LOCKED = "QUOTE_LOCKED"
    SHOWROOM_LIST = "SHOWROOM_LIST"


class KitStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSEMBLED = "ASSEMBLED"
    STAGED = "STAGED"
    RELEASED = "RELEASED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    FULL = "FULL"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CREDITED = "CREDITED"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    CARD = "CARD"


class Branch(TypedDict, total=False):
    id: str
    name: str
    code: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    description: str
    category: str
    list_price_cents: int
    cost_cents: int
    manufacturer_name: str
    cubes_per_unit: int
    is_cut_to_order: bool
    is_special_order: bool
    substitute_group: Optional[str]
    promo_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ContractorAccount(TypedDict, total=False):
    id: str
    company_name: str
    pricing_tier: str
    terms: str
    credit_limit_cents: int
    status: str
    outstanding_balance_cents: int
    forward_exposure_cents: int
    available_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class ManufacturerProgram(TypedDict, total=False):
    id: str
    manufacturer_name: str
    period_start: str
    period_end: str
    tiers: List[Dict[str, int]]
    committed_stock_value_cents: int
    purchases_cents: int
    attained_rebate_pct: Optional[int]
    earned_rebate_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryStock(TypedDict, total=False):
    id: str
    branch_id: str
    product_id: str
    on_hand: int
    reserved: int
    available: int
    created_at: str
    updated_at: str
    version: int


class StockReceipt(TypedDict, total=False):
    id: str
    branch_id: str
    lines: List[Dict[str, Any]]
    received_at: str
    posted_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    method: str
    allocations: Optional[List[Dict[str, Any]]]
    applied_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    account_id: str
    branch_id: str
    job_name: str
    valid_until: str
    lines: List[Dict[str, Any]]
    revision_no: int
    supersedes_quote_id: Optional[str]
    status: str
    volume_discount_pct: int
    subtotal_cents: int
    discount_cents: int
    freight_cents: int
    total_cents: int
    awarded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelectionSheet(TypedDict, total=False):
    id: str
    account_id: str
    branch_id: str
    customer_name: str
    selections: List[Dict[str, Any]]
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    account_id: str
    branch_id: str
    quote_id: Optional[str]
    sheet_id: Optional[str]
    delivery_slot_id: Optional[str]
    source: str
    job_name: Optional[str]
    will_call: bool
    payment_status: str
    fulfillment_status: str
    volume_discount_pct: int
    subtotal_cents: int
    discount_cents: int
    freight_cents: int
    total_cents: int
    cubes_total: int
    invoiced_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    product_id: str
    kit_id: Optional[str]
    qty_ordered: int
    cut_length_ft: Optional[int]
    price_override_cents: Optional[int]
    unit_price_cents: int
    price_source: str
    qty_allocated: int
    qty_backordered: int
    qty_fulfilled: int
    qty_returned: int
    status: str
    substitute_status: str
    proposed_substitute_product_id: Optional[str]
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Kit(TypedDict, total=False):
    id: str
    order_id: str
    floor_label: str
    status: str
    staging_bin: Optional[str]
    staged_window_start: Optional[str]
    staged_window_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliverySlot(TypedDict, total=False):
    id: str
    branch_id: str
    truck_label: str
    window_start: str
    window_end: str
    capacity_cubes: int
    booked_cubes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnRequest(TypedDict, total=False):
    id: str
    order_id: str
    reason: str
    lines: List[Dict[str, Any]]
    status: str
    submitted_by: Optional[str]
    decided_by: Optional[str]
    submitted_at: Optional[str]
    restocking_fee_cents: int
    credit_cents: int
    created_at: str
    updated_at: str
    version: int
