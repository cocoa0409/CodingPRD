"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ─── Enumerations ─────────────────────────────────────


class UserRole(str, Enum):
    DISTRIBUTION_ADMIN = "DistributionAdmin"
    CUSTOMER_BUYER = "CustomerBuyer"
    CUSTOMER_APPROVER = "CustomerApprover"
    BRANCH_MANAGER = "BranchManager"
    VENDOR_REP = "VendorRep"


class PriceTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class ItemClass(str, Enum):
    STOCKED = "STOCKED"
    SPECIAL_ORDER = "SPECIAL_ORDER"
    NON_RETURNABLE = "NON_RETURNABLE"


class HazmatRestriction(str, Enum):
    NONE = "NONE"
    GROUND_ONLY = "GROUND_ONLY"
    WILL_CALL_ONLY = "WILL_CALL_ONLY"


class RuleType(str, Enum):
    FIXED_PRICE = "FIXED_PRICE"
    DISCOUNT_PCT = "DISCOUNT_PCT"


class PriceRuleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class RebateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class LocationType(str, Enum):
    BRANCH = "BRANCH"
    CENTRAL = "CENTRAL"


class CartStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONVERTED = "CONVERTED"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    ALLOCATED = "ALLOCATED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    READY_FOR_WILL_CALL = "READY_FOR_WILL_CALL"
    SHIPPED = "SHIPPED"
    FULFILLED = "FULFILLED"


class FulfillmentMethod(str, Enum):
    WILL_CALL = "WILL_CALL"
    SAME_DAY = "SAME_DAY"
    STANDARD = "STANDARD"


class FulfillmentSource(str, Enum):
    UNRESOLVED = "UNRESOLVED"
    BRANCH_ONLY = "BRANCH_ONLY"
    SPLIT_STOCK = "SPLIT_STOCK"
    DROP_SHIP_ONLY = "DROP_SHIP_ONLY"
    BACKORDER_ONLY = "BACKORDER_ONLY"
    MIXED = "MIXED"


class MarginStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"


class ReturnCondition(str, Enum):
    RESALEABLE = "RESALEABLE"
    DAMAGED = "DAMAGED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECEIVED = "RECEIVED"
    CREDITED = "CREDITED"


# ─── Entity TypedDicts ────────────────────────────────
# Every resource carries the standard system-managed fields of PRD §2.5:
# id, created_at, updated_at, version.


class CustomerAccount(TypedDict, total=False):
    id: str
    account_number: str
    display_name: str
    price_tier: str
    is_national_account: bool
    credit_limit_cents: int
    approval_threshold_cents: int
    primary_ship_to_state: str
    status: str
    net_spend_cents: int
    open_credit_exposure_cents: int
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    sku: str
    description: str
    item_class: str
    hazmat_restriction: str
    restricted_states: List[str]
    list_price_cents: int
    drop_ship_eligible: bool
    vendor_cost_estimate_cents: int
    vendor_freight_estimate_cents: int
    created_at: str
    updated_at: str
    version: int


class PriceMatrixRule(TypedDict, total=False):
    id: str
    customer_tier: str
    item_id: Optional[str]
    item_class: Optional[str]
    rule_type: str
    contract_unit_price_cents: Optional[int]
    discount_pct: Optional[float]
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateTier(TypedDict):
    threshold_cents: int
    rebate_bps: int


class RebateAgreement(TypedDict, total=False):
    id: str
    customer_id: str
    period_start: str
    period_end: str
    tiers: List[RebateTier]
    status: str
    accrued_spend_cents: int
    current_tier_index: int
    provisional_rebate_cents: int
    final_rebate_cents: Optional[int]
    true_up_delta_cents: Optional[int]
    settled_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StockLocation(TypedDict, total=False):
    id: str
    location_code: str
    location_type: str
    region_state: str
    same_day_cutoff_minute: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StockBalance(TypedDict, total=False):
    id: str
    location_id: str
    item_id: str
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class CartLine(TypedDict):
    item_id: str
    qty: int


class RequisitionCart(TypedDict, total=False):
    id: str
    customer_id: str
    punch_out_external_ref: Optional[str]
    lines: List[CartLine]
    estimated_total_cents: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_id: str
    fulfillment_branch_id: str
    source_cart_id: Optional[str]
    fulfillment_method: str
    status: str
    fulfillment_status: str
    subtotal_cents: int
    freight_cents: int
    total_cents: int
    promise_date: Optional[str]
    sla_breach: bool
    confirmed_at: Optional[str]
    fulfilled_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    item_id: str
    qty: int
    unit_price_cents: int
    line_total_cents: int
    qty_branch: int
    qty_central: int
    qty_drop_ship: int
    qty_backordered: int
    fulfillment_source: str
    qty_vendor_confirmed: int
    vendor_cost_actual_cents: Optional[int]
    freight_actual_cents: Optional[int]
    provisional_margin_cents: Optional[int]
    final_margin_cents: Optional[int]
    margin_status: str
    created_at: str
    updated_at: str
    version: int


class ReturnLine(TypedDict):
    order_line_id: str
    qty: int
    condition: str


class ReturnAuthorization(TypedDict, total=False):
    id: str
    order_id: str
    lines: List[ReturnLine]
    status: str
    rejection_reason: Optional[str]
    credit_cents: Optional[int]
    restocking_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


Scenario = Dict[str, Any]
