"""Domain types for the Wire & Cable Distribution API.

Entity TypedDicts, status enumerations and the operator role enumeration,
all taken from the PRD.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ──────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_REP = "SalesRep"
    BRANCH_OPS = "BranchOps"
    DRIVER = "Driver"
    CREDIT_MANAGER = "CreditManager"
    CUSTOMER = "Customer"


# ─── Status enumerations ───────────────────────────────────────────────────

class CustomerCreditStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class ConductorMetal(str, Enum):
    COPPER = "COPPER"
    ALUMINUM = "ALUMINUM"


class PutUp(str, Enum):
    MASTER_REEL = "MASTER_REEL"
    CUT = "CUT"


class ReelType(str, Enum):
    MASTER = "MASTER"
    REMNANT = "REMNANT"


class ReelStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ALLOCATED_PARTIAL = "ALLOCATED_PARTIAL"
    ON_JOBSITE = "ON_JOBSITE"
    DEPLETED = "DEPLETED"
    SCRAPPED = "SCRAPPED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"
    VOIDED = "VOIDED"


class QuoteVoidReason(str, Enum):
    INDEX_SHOCK = "INDEX_SHOCK"
    CREDIT_HOLD = "CREDIT_HOLD"


class FulfillmentStatus(str, Enum):
    PENDING_ALLOCATION = "PENDING_ALLOCATION"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    ALLOCATED = "ALLOCATED"
    STAGED = "STAGED"
    DELIVERED = "DELIVERED"
    HELD = "HELD"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    CREDITED = "CREDITED"
    VOIDED = "VOIDED"


class AllocationPolicy(str, Enum):
    MINIMIZE_REMNANT = "MINIMIZE_REMNANT"
    FEWEST_REELS = "FEWEST_REELS"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class CommitMode(str, Enum):
    CUT = "CUT"
    PICK = "PICK"


class OrderLineAllocationStatus(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    SHORT = "SHORT"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"


class DeliveryRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"


class ReelHandling(str, Enum):
    TAILGATE = "TAILGATE"
    BOOM_LIFT = "BOOM_LIFT"
    FORKLIFT = "FORKLIFT"


class ReelCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


# ─── Entity shapes ─────────────────────────────────────────────────────────
# Every resource below carries id, created_at, updated_at and version
# (PRD §2.4) except CopperIndexEntry, which is an immutable market record
# carrying only id and created_at.

class Branch(TypedDict):
    id: str
    name: str
    region_code: str
    concurrent_cut_capacity: int
    delivery_surcharge_cents: int
    scrap_ft_ytd: float
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    credit_limit_cents: int
    open_balance_cents: int
    deposit_liability_cents: int
    available_credit_cents: int
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class CableProduct(TypedDict):
    id: str
    part_number: str
    conductor_metal: str
    copper_lbs_per_1000ft: float
    base_price_cents_per_ft: int
    min_cut_length_ft: int
    cut_charge_cents: int
    reel_deposit_cents: int
    master_reel_length_ft: int
    reel_weight_lbs: float
    allowed_put_ups: List[str]
    created_at: str
    updated_at: str
    version: int


class CopperIndexEntry(TypedDict):
    """Immutable market record — no updated_at and no version (PRD §2.4)."""
    id: str
    effective_date: str
    price_cents_per_lb: int
    published_by_user_id: str
    voided_quote_count: int
    created_at: str


class Truck(TypedDict):
    id: str
    branch_id: str
    truck_code: str
    has_boom_lift: bool
    max_reel_slots: int
    created_at: str
    updated_at: str
    version: int


class Reel(TypedDict):
    id: str
    product_id: str
    branch_id: str
    parent_reel_id: Optional[str]
    reel_type: str
    lot_code: str
    nominal_length_ft: float
    current_length_ft: float
    allocated_length_ft: float
    available_length_ft: float
    scrap_ft: float
    status: str
    delivered_sales_order_id: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    customer_id: str
    branch_id: str
    copper_index_entry_id: Optional[str]
    created_by_user_id: str
    issued_by_user_id: Optional[str]
    status: str
    issued_at: Optional[str]
    valid_until: Optional[str]
    void_reason: Optional[str]
    line_subtotal_cents: int
    physical_reel_count: int
    gross_freight_cents: int
    rebate_pct: float
    rebate_cents: int
    freight_cents: int
    quoted_total_cents: int
    deposit_quoted_cents: int
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict):
    id: str
    quote_id: str
    product_id: str
    line_number: int
    put_up: str
    requested_length_ft: float
    parallel_set_size: int
    billable_length_ft: float
    reel_count: int
    copper_adder_cents_per_ft: float
    metal_cents: int
    base_cents: int
    cut_charge_cents_total: int
    deposit_cents_total: int
    quoted_extended_cents: int
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict):
    id: str
    quote_id: str
    customer_id: str
    branch_id: str
    fulfillment_status: str
    billing_status: str
    allocation_policy: str
    line_subtotal_cents: int
    freight_cents: int
    rebate_cents: int
    quoted_total_cents: int
    invoiced_total_cents: Optional[int]
    metal_variance_cents: Optional[int]
    deposit_charged_cents: int
    deposit_credited_cents: int
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    sales_order_id: str
    product_id: str
    line_number: int
    put_up: str
    requested_length_ft: float
    parallel_set_size: int
    billable_length_ft: float
    required_length_ft: float
    allocated_length_ft: float
    allocation_status: str
    lot_code: Optional[str]
    returnable: bool
    quoted_extended_cents: int
    invoiced_extended_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    order_line_id: str
    sales_order_id: str
    reel_id: str
    remnant_reel_id: Optional[str]
    sequence_no: int
    length_ft: float
    status: str
    commit_mode: Optional[str]
    cut_window_start: Optional[str]
    cut_window_end: Optional[str]
    cut_charge_applied_cents: int
    scrap_ft: float
    created_at: str
    updated_at: str
    version: int


class DeliveryRun(TypedDict):
    id: str
    sales_order_id: str
    truck_id: str
    branch_id: str
    window_start: str
    window_end: str
    jobsite_address: str
    jobsite_has_forklift: bool
    heaviest_reel_lbs: float
    reel_handling: str
    status: str
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
