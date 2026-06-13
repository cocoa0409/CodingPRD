"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1) — exactly six, spelled precisely.
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROCUREMENT_ADMIN = "ProcurementAdmin"
    BUYER = "Buyer"
    APPROVER = "Approver"
    RECEIVER = "Receiver"
    MATCHER = "Matcher"
    PAYABLES_CLERK = "PayablesClerk"


# --------------------------------------------------------------------------
# Status enums (PRD §3 workflows).
# --------------------------------------------------------------------------
class SpendCategoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class VendorStatus(str, Enum):
    APPROVED = "APPROVED"
    PROBATION = "PROBATION"
    BLOCKED = "BLOCKED"


class RequisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ApprovalStepStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SKIPPED = "SKIPPED"


class ApprovalRole(str, Enum):
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"
    CFO = "CFO"


class RFQStatus(str, Enum):
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"
    CLOSED_NO_AWARD = "CLOSED_NO_AWARD"


class QuoteStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    VOIDED = "VOIDED"


class PurchaseOrderType(str, Enum):
    STANDARD = "STANDARD"
    BLANKET = "BLANKET"


class PurchaseOrderStatus(str, Enum):
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReleaseOrderStatus(str, Enum):
    OPEN = "OPEN"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class GoodsReceiptStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class InvoiceMatchStatus(str, Enum):
    UNMATCHED = "UNMATCHED"
    MATCHED = "MATCHED"
    EXCEPTION = "EXCEPTION"


class InvoicePaymentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED_FOR_PAY = "APPROVED_FOR_PAY"
    PAID = "PAID"
    REJECTED = "REJECTED"


class MatchExceptionReason(str, Enum):
    PRICE_OVER_TOLERANCE = "PRICE_OVER_TOLERANCE"
    QTY_OVER_TOLERANCE = "QTY_OVER_TOLERANCE"
    AMOUNT_OVER_TOLERANCE = "AMOUNT_OVER_TOLERANCE"
    NO_RECEIPT = "NO_RECEIPT"


class MatchExceptionStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class OnTimeVariant(str, Enum):
    STRICT = "STRICT"
    GRACE = "GRACE"


class VendorScorecardStatus(str, Enum):
    FINAL = "FINAL"


# --------------------------------------------------------------------------
# Entity TypedDicts. All entities are fully versioned (PRD §2.4): every
# resource carries id, created_at, updated_at, version.
# --------------------------------------------------------------------------
class SpendCategory(TypedDict):
    id: str
    name: str
    code: str
    approval_threshold_cents: int
    director_threshold_cents: int
    preferred_vendor_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict):
    id: str
    name: str
    tax_id: str
    grace_days: int
    exception_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Requisition(TypedDict):
    id: str
    requester_id: str
    spend_category_id: str
    title: str
    lines: List[dict]
    estimated_total_cents: int
    committed_total_cents: Optional[int]
    required_levels: int
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ApprovalStep(TypedDict):
    id: str
    requisition_id: str
    level: int
    required_role: str
    decided_by_id: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RFQ(TypedDict):
    id: str
    requisition_id: str
    round_index: int
    open_at: str
    close_at: str
    awarded_quote_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    rfq_id: str
    vendor_id: str
    submitted_at: str
    unit_prices: List[dict]
    quoted_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict):
    id: str
    vendor_id: str
    spend_category_id: str
    requisition_id: Optional[str]
    source_quote_id: Optional[str]
    po_type: str
    lines: Optional[List[dict]]
    total_amount_cents: int
    ceiling_amount_cents: Optional[int]
    remaining_amount_cents: Optional[int]
    valid_from: Optional[str]
    valid_to: Optional[str]
    is_maverick: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseOrder(TypedDict):
    id: str
    blanket_po_id: str
    amount_cents: int
    lines: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class GoodsReceipt(TypedDict):
    id: str
    purchase_order_id: str
    release_order_id: Optional[str]
    received_lines: List[dict]
    received_at: str
    posted_by_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    vendor_id: str
    purchase_order_id: str
    goods_receipt_id: str
    invoice_number: str
    lines: List[dict]
    invoice_total_cents: int
    match_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class MatchException(TypedDict):
    id: str
    invoice_id: str
    vendor_id: str
    reason: str
    detail: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorScorecard(TypedDict):
    id: str
    vendor_id: str
    period_start: str
    period_end: str
    on_time_variant: str
    on_time_rate_pct: int
    price_compliance_pct: int
    exception_pct: int
    composite_score: int
    status: str
    created_at: str
    updated_at: str
    version: int
