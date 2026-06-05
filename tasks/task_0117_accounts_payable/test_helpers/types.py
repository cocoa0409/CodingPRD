"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    AP_MANAGER = "APManager"
    AP_CLERK = "APClerk"
    APPROVER = "Approver"
    AUDITOR = "Auditor"


# ---------------------------------------------------------------------------
# Status / enum vocabularies (PRD §3)
# ---------------------------------------------------------------------------
class PaymentMethod(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    CARD = "CARD"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"


class PurchaseOrderStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class GoodsReceiptStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"


class InvoiceStatus(str, Enum):
    CAPTURED = "CAPTURED"
    CODING_REVIEW = "CODING_REVIEW"
    MATCHED = "MATCHED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class MatchType(str, Enum):
    TWO_WAY = "TWO_WAY"
    THREE_WAY = "THREE_WAY"
    NON_PO = "NON_PO"


class MatchExceptionReason(str, Enum):
    PRICE_VARIANCE = "PRICE_VARIANCE"
    QTY_VARIANCE = "QTY_VARIANCE"


class MatchExceptionResolution(str, Enum):
    PENDING = "PENDING"
    RESOLVED = "RESOLVED"
    WRITTEN_OFF = "WRITTEN_OFF"
    ESCALATED = "ESCALATED"


class ApprovalStepStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PaymentBatchStatus(str, Enum):
    BUILDING = "BUILDING"
    RELEASED = "RELEASED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"


class AccrualStatus(str, Enum):
    BOOKED = "BOOKED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Entities with the full common-field set carry id/created_at/updated_at/version.
# Lightweight records (GL account, approval route, audit event) carry ONLY
# id + created_at (PRD §2.4).
# ---------------------------------------------------------------------------
class Vendor(TypedDict):
    id: str
    legal_name: str
    payment_method: str
    is_1099: bool
    tax_id: Optional[str]
    early_pay_terms_pct: float
    early_pay_window_days: int
    net_terms_days: int
    status: str
    ytd_1099_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class GLAccount(TypedDict):
    # Lightweight record: id + created_at only (no updated_at / version).
    id: str
    code: str
    name: str
    is_postable: bool
    created_at: str


class PurchaseOrder(TypedDict):
    id: str
    vendor_id: str
    gl_account_code: str
    ordered_amount_cents: int
    received_amount_cents: int
    matched_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GoodsReceipt(TypedDict):
    id: str
    po_id: str
    received_amount_cents: int
    received_date: str
    coverage_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    vendor_id: str
    po_id: Optional[str]
    invoice_number: str
    invoice_date: str
    ocr_confidence: float
    total_amount_cents: int
    match_type: Optional[str]
    variance_cents: int
    due_date: str
    discount_deadline: Optional[str]
    coded_by: Optional[str]
    approved_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    id: str
    invoice_id: str
    gl_account_code: str
    amount_cents: int
    description: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchException(TypedDict):
    id: str
    invoice_id: str
    reason: str
    variance_cents: int
    resolution: str
    resolved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovalRoute(TypedDict):
    # Lightweight record: id + created_at only (no updated_at / version).
    id: str
    min_amount_cents: int
    max_amount_cents: int
    required_levels: int
    created_at: str


class ApprovalStep(TypedDict):
    id: str
    invoice_id: str
    level: int
    status: str
    acted_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentBatch(TypedDict):
    id: str
    payment_method: str
    run_date: str
    total_disbursed_cents: int
    status: str
    released_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    batch_id: str
    invoice_id: str
    gross_amount_cents: int
    discount_taken_cents: int
    net_amount_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class Accrual(TypedDict):
    id: str
    po_id: str
    period_label: str
    period_start: str
    period_end: str
    estimated_cents: int
    final_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict):
    # Lightweight record: id + created_at only (no updated_at / version).
    id: str
    invoice_id: str
    event_type: str
    actor_user_id: str
    created_at: str
