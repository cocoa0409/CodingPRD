"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SALES_REP = "SalesRep"
    BRANCH_MANAGER = "BranchManager"
    CREDIT_MANAGER = "CreditManager"
    WAREHOUSE_MANAGER = "WarehouseManager"
    DISPATCHER = "Dispatcher"
    REBATE_CLERK = "RebateClerk"
    CONTRACTOR = "Contractor"


class SellUom(str, Enum):
    EA = "EA"
    FOOT = "FOOT"


class PricingMode(str, Enum):
    FIRM_PRICE = "FIRM_PRICE"
    ESCALATION = "ESCALATION"


class JobAccountStatus(str, Enum):
    OPEN = "OPEN"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    EXPIRED = "EXPIRED"


class SubstitutionRequestStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReleaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CREDIT_APPROVED = "CREDIT_APPROVED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    ALLOCATED = "ALLOCATED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class ReleaseLineStatus(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class BackorderAllocationStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class RebateClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# All resources carry id + created_at + updated_at + version (PRD section 2.4).


class Contractor(TypedDict):
    id: str
    name: str
    credit_limit_cents: int
    invoiced_balance_cents: int
    committed_balance_cents: int
    credit_used_cents: int
    created_at: str
    updated_at: str
    version: int


class CatalogItem(TypedDict):
    id: str
    sku: str
    manufacturer_name: str
    sell_uom: str
    list_price_cents: float
    reel_length_ft: Optional[int]
    min_cut_ft: Optional[int]
    cut_charge_cents: Optional[int]
    stock_on_hand: float
    stock_allocated: float
    created_at: str
    updated_at: str
    version: int


class JobAccount(TypedDict):
    id: str
    contractor_id: str
    job_name: str
    jobsite_address: str
    pricing_mode: str
    escalation_cap_pct: Optional[float]
    lien_waiver_required: bool
    lien_waiver_expires_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    job_account_id: str
    valid_until: str
    revision_no: int
    status: str
    award_month: Optional[str]
    award_index_value: Optional[float]
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict):
    id: str
    quote_id: str
    catalog_item_id: str
    qty: float
    unit_price_cents: float
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict):
    id: str
    quote_line_id: str
    proposed_item_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Release(TypedDict):
    id: str
    job_account_id: str
    quote_id: str
    status: str
    estimated_total_cents: int
    billed_total_cents: Optional[int]
    truck_id: Optional[str]
    delivery_date: Optional[str]
    window_start_hour: Optional[int]
    window_end_hour: Optional[int]
    invoiced_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseLine(TypedDict):
    id: str
    release_id: str
    catalog_item_id: str
    qty_requested: float
    qty_allocated: float
    qty_shipped: float
    billed_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BackorderAllocation(TypedDict):
    id: str
    release_line_id: str
    catalog_item_id: str
    qty_open: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RebateTier(TypedDict):
    threshold_cents: int
    rebate_pct: float


class RebateProgram(TypedDict):
    id: str
    manufacturer_name: str
    period_start: str
    period_end: str
    tiers: List[RebateTier]
    created_at: str
    updated_at: str
    version: int


class RebateClaim(TypedDict):
    id: str
    rebate_program_id: str
    status: str
    provisional_amount_cents: int
    qualifying_base_cents: Optional[int]
    tier_pct_applied: Optional[float]
    final_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int
