"""Domain types: entity TypedDicts, status enums, role enum (PRD-exact names)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class PressType(str, Enum):
    WEB = "WEB"
    SHEETFED = "SHEETFED"


class BindingMethod(str, Enum):
    SADDLE_STITCH = "SADDLE_STITCH"
    PERFECT_BIND = "PERFECT_BIND"
    CASE_BIND = "CASE_BIND"
    PLASTIC_COIL = "PLASTIC_COIL"


class FulfillmentType(str, Enum):
    SHIP = "SHIP"
    MAIL = "MAIL"


class FinishingOption(str, Enum):
    PERF = "PERF"
    SCORE = "SCORE"
    UV_COAT = "UV_COAT"
    LAMINATE = "LAMINATE"
    FOIL = "FOIL"
    DIE_CUT = "DIE_CUT"


class ProductionStatus(str, Enum):
    PREPRESS = "PREPRESS"
    PROOF_REVIEW = "PROOF_REVIEW"
    PLATED = "PLATED"
    PRESS_SCHEDULED = "PRESS_SCHEDULED"
    BINDERY = "BINDERY"
    READY_TO_SHIP = "READY_TO_SHIP"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    NOT_BILLABLE = "NOT_BILLABLE"


class ProofStatus(str, Enum):
    AWAITING_CUSTOMER = "AWAITING_CUSTOMER"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class PaperGrade(str, Enum):
    COATED = "COATED"
    UNCOATED = "UNCOATED"
    NEWSPRINT = "NEWSPRINT"


class POSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_REPLENISH = "AUTO_REPLENISH"


class POStatus(str, Enum):
    ORDERED = "ORDERED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class PressStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DOWN = "DOWN"


class PressRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class GangRunStatus(str, Enum):
    FORMING = "FORMING"
    LOCKED = "LOCKED"
    CONSUMED = "CONSUMED"


class BinderyOperation(str, Enum):
    FOLD = "FOLD"
    STITCH = "STITCH"
    TRIM = "TRIM"
    PERF = "PERF"
    SCORE = "SCORE"
    UV_COAT = "UV_COAT"
    LAMINATE = "LAMINATE"
    FOIL = "FOIL"
    DIE_CUT = "DIE_CUT"
    COLLATE = "COLLATE"
    PAD = "PAD"


class BinderyTicketStatus(str, Enum):
    QUEUED = "QUEUED"
    COMPLETE = "COMPLETE"


class DestinationEntry(str, Enum):
    NONE = "NONE"
    BMC = "BMC"
    SCF = "SCF"
    DDU = "DDU"


class MailDropStatus(str, Enum):
    PLANNED = "PLANNED"
    PRESORTED = "PRESORTED"
    DROPPED = "DROPPED"


class InvoiceKind(str, Enum):
    PRODUCTION = "PRODUCTION"
    CANCELLATION_FEE = "CANCELLATION_FEE"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class ClaimedDefect(str, Enum):
    MISREGISTER = "MISREGISTER"
    COLOR_SHIFT = "COLOR_SHIFT"
    TRIM_ERROR = "TRIM_ERROR"
    BINDING_DEFECT = "BINDING_DEFECT"
    PAPER_STOCK_WRONG = "PAPER_STOCK_WRONG"
    SHORTAGE = "SHORTAGE"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ClaimResolution(str, Enum):
    REPRINT = "REPRINT"
    CREDIT = "CREDIT"


class CustomerPosture(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class UserRole(str, Enum):
    ESTIMATOR = "Estimator"
    CUSTOMER = "Customer"
    PREPRESS_OPERATOR = "PrepressOperator"
    PRESS_SCHEDULER = "PressScheduler"
    PURCHASING_MANAGER = "PurchasingManager"
    MAIL_SPECIALIST = "MailSpecialist"
    PLANT_MANAGER = "PlantManager"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all entities carry common fields
# (id, created_at, updated_at, version) per PRD §2.4.
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    default_tolerance_pct: int
    exposure_cents: int
    posture: str
    reprint_credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Signature(TypedDict):
    name: str
    pages: int
    up_count: int
    paper_stock_id: str
    make_ready_cents: int
    rate_per_thousand_cents: int


class Estimate(TypedDict, total=False):
    id: str
    customer_id: str
    job_name: str
    quantity_ordered: int
    press_type: str
    binding_method: str
    fulfillment_type: str
    signatures: List[Dict[str, Any]]
    finishing_options: List[str]
    press_spoilage_pct: float
    bindery_spoilage_pct: float
    included_proof_rounds: int
    quote_valid_days: int
    due_date: str
    impressions_per_signature: List[int]
    total_impressions: int
    make_ready_total_cents: int
    running_cost_cents: int
    paper_sheets_total: int
    paper_cost_cents: int
    finishing_cost_cents: int
    subtotal_cents: int
    discount_pct: float
    total_price_cents: int
    status: str
    quoted_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict, total=False):
    id: str
    estimate_id: Optional[str]
    parent_job_id: Optional[str]
    customer_id: str
    zero_charge: bool
    quantity_ordered: int
    due_date: str
    press_type: str
    fulfillment_type: str
    binding_method: str
    signatures: List[Dict[str, Any]]
    press_spoilage_pct: float
    bindery_spoilage_pct: float
    included_proof_rounds: int
    tolerance_pct: int
    total_impressions: int
    make_ready_total_cents: int
    total_price_cents: int
    discount_pct: float
    subtotal_cents: int
    production_status: str
    billing_status: str
    gang_run_id: Optional[str]
    allocated_make_ready_cents: Optional[int]
    delivered_quantity: Optional[int]
    proof_rounds_used: int
    created_at: str
    updated_at: str
    version: int


class Proof(TypedDict, total=False):
    id: str
    job_id: str
    file_uri: str
    round_number: int
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaperStock(TypedDict, total=False):
    id: str
    name: str
    grade: str
    cost_per_sheet_cents: int
    reorder_threshold_sheets: int
    reorder_quantity_sheets: int
    available_sheets: int
    created_at: str
    updated_at: str
    version: int


class PaperPurchaseOrder(TypedDict, total=False):
    id: str
    paper_stock_id: str
    ordered_sheets: int
    cost_per_sheet_cents: int
    source: str
    received_sheets_total: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaperLot(TypedDict, total=False):
    id: str
    paper_stock_id: str
    paper_purchase_order_id: str
    received_sheets: int
    damaged_sheets: int
    reserved_sheets: int
    consumed_sheets: int
    remaining_sheets: int
    created_at: str
    updated_at: str
    version: int


class Press(TypedDict, total=False):
    id: str
    name: str
    press_type: str
    rated_impressions_per_hour: int
    make_ready_minutes_base: int
    washup_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PressRun(TypedDict, total=False):
    id: str
    press_id: str
    job_id: Optional[str]
    gang_run_id: Optional[str]
    run_quantity: int
    scheduled_start: str
    planned_impressions: int
    planned_sheets: int
    duration_minutes: int
    scheduled_end: str
    status: str
    gross_impressions: Optional[int]
    sheets_used: Optional[int]
    waste_sheets: Optional[int]
    created_at: str
    updated_at: str
    version: int


class GangMember(TypedDict, total=False):
    job_id: str
    added_at: str
    allocated_make_ready_cents: Optional[int]


class GangRun(TypedDict, total=False):
    id: str
    paper_stock_id: str
    press_type: str
    anchor_due_date: str
    status: str
    members: List[Dict[str, Any]]
    make_ready_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BinderyTicket(TypedDict, total=False):
    id: str
    job_id: str
    operation: str
    sequence_no: int
    pieces_completed: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ZipCount(TypedDict):
    zip5: str
    pieces: int


class TierBreakdown(TypedDict):
    five_digit_pieces: int
    three_digit_pieces: int
    aadc_pieces: int


class MailDrop(TypedDict, total=False):
    id: str
    job_id: str
    drop_date: str
    destination_entry: str
    piece_weight_oz: float
    zip_counts: List[Dict[str, Any]]
    total_pieces: int
    tier_breakdown: Optional[Dict[str, int]]
    postage_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    job_id: str
    customer_id: str
    kind: str
    quantity_ordered: int
    delivered_quantity: int
    billable_quantity: int
    base_amount_cents: int
    postage_cents: int
    proof_overage_cents: int
    shortage_credit_cents: int
    gang_make_ready_allocated_cents: Optional[int]
    total_due_cents: int
    amount_paid_cents: int
    credit_applied_cents: int
    amount_outstanding_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReprintClaim(TypedDict, total=False):
    id: str
    job_id: str
    invoice_id: Optional[str]
    claimed_defect: str
    defect_qty: int
    status: str
    reviewed_by: Optional[str]
    resolution: Optional[str]
    liability_pct: Optional[int]
    provisional_credit_cents: Optional[int]
    final_credit_cents: Optional[int]
    reprint_job_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
