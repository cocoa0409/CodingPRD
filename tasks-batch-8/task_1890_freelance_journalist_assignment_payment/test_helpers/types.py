"""Domain types: entity TypedDicts, status enums, role enum (PRD sections 2-4)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD section 2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    DESK_ADMIN = "DeskAdmin"
    EDITOR = "Editor"
    CONTRIBUTOR = "Contributor"
    FINANCE_USER = "FinanceUser"
    VERIFICATION_EDITOR = "VerificationEditor"


# ---------------------------------------------------------------------------
# Status enums (PRD section 3)
# ---------------------------------------------------------------------------

class ContributorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class TaxResidency(str, Enum):
    DOMESTIC_US = "DOMESTIC_US"
    FOREIGN = "FOREIGN"


class RateAgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class PricingMode(str, Enum):
    PER_WORD = "PER_WORD"
    FLAT = "FLAT"


class RightsKind(str, Enum):
    FIRST = "FIRST"
    ONE_TIME = "ONE_TIME"
    ALL = "ALL"


class EditorialStatus(str, Enum):
    DRAFT = "DRAFT"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    ACCEPTED_FOR_PUBLICATION = "ACCEPTED_FOR_PUBLICATION"
    KILLED = "KILLED"
    REJECTED_AFTER_FLAG = "REJECTED_AFTER_FLAG"


class PaymentStatus(str, Enum):
    UNINVOICED = "UNINVOICED"
    INVOICED = "INVOICED"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    VOID = "VOID"


class KillFeeTier(str, Enum):
    PRE_DELIVERY = "PRE_DELIVERY"
    POST_DELIVERY = "POST_DELIVERY"


class ExpenseCategory(str, Enum):
    TRAVEL = "TRAVEL"
    MEALS = "MEALS"
    EQUIPMENT = "EQUIPMENT"
    OTHER = "OTHER"


class ExpenseClaimStatus(str, Enum):
    PRE_APPROVAL_REQUESTED = "PRE_APPROVAL_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUBMITTED = "SUBMITTED"
    REIMBURSABLE = "REIMBURSABLE"
    DENIED = "DENIED"
    PAID = "PAID"


class CheckerKind(str, Enum):
    PLAGIARISM = "PLAGIARISM"
    AI_CONTENT = "AI_CONTENT"


class VerificationReportStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    CONFIRMED_VIOLATION = "CONFIRMED_VIOLATION"
    DISMISSED = "DISMISSED"


class RightsPurchaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERTED = "REVERTED"


class TaxDocKind(str, Enum):
    W9 = "W9"
    W8BEN = "W8BEN"


class TaxDocumentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    APPROVED = "APPROVED"
    BATCHED = "BATCHED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    VOID = "VOID"


class PaymentBatchStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class LedgerEntryKind(str, Enum):
    FEE_CREDIT = "FEE_CREDIT"
    EXPENSE_CREDIT = "EXPENSE_CREDIT"
    WITHHOLDING_DEBIT = "WITHHOLDING_DEBIT"
    LATE_FEE_CREDIT = "LATE_FEE_CREDIT"
    REUSE_ROYALTY_CREDIT = "REUSE_ROYALTY_CREDIT"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Contributor(TypedDict, total=False):
    id: str
    legal_name: str
    pen_name: str
    email: str
    tax_residency: str
    status: str
    ytd_gross_cents: int
    reportable_threshold_crossed: bool
    backup_withholding_flag: bool
    created_at: str
    updated_at: str
    version: int


class RateAgreement(TypedDict, total=False):
    id: str
    contributor_id: str
    pricing_mode: str
    per_word_rate_cents: Optional[int]
    flat_fee_cents: Optional[int]
    kill_fee_pct_num: int
    rights_default: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    contributor_id: str
    rate_agreement_id: Optional[str]
    title: str
    brief: str
    commissioned_word_count: int
    final_word_count: Optional[int]
    deadline_utc: str
    editorial_status: str
    payment_status: str
    kill_fee_tier: Optional[str]
    agreed_fee_cents: int
    final_fee_cents: Optional[int]
    verification_cleared: bool
    late_flag: bool
    created_at: str
    updated_at: str
    version: int


class ExpenseClaim(TypedDict, total=False):
    id: str
    assignment_id: str
    category: str
    requested_cents: int
    approved_cents: Optional[int]
    claimed_cents: Optional[int]
    receipt_attached: bool
    status: str
    reimbursable_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class VerificationReport(TypedDict, total=False):
    id: str
    assignment_id: str
    checker_kind: str
    similarity_score_bps: int
    ai_probability_bps: int
    status: str
    adjudication_note: str
    created_at: str
    updated_at: str
    version: int


class RightsPurchase(TypedDict, total=False):
    id: str
    assignment_id: str
    rights_kind: str
    reuse_count: int
    reuse_fee_cents_total: int
    buyout_uplift_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxDocument(TypedDict, total=False):
    id: str
    contributor_id: str
    doc_kind: str
    treaty_country: Optional[str]
    tin_last4: str
    submitted_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    assignment_id: str
    submitted_by_contributor_id: str
    fee_claim_cents: int
    expense_claim_cents: int
    gross_cents: int
    withholding_cents: int
    net_payable_cents: int
    payment_terms_days: int
    due_date_utc: str
    status: str
    late_fee_cents: int
    payment_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentBatch(TypedDict, total=False):
    id: str
    scheduled_pay_date: str
    status: str
    total_gross_cents: int
    total_withholding_cents: int
    total_net_cents: int
    locked_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    # Append-only postings: carry id + created_at only — no updated_at, no version
    # (PRD section 2.4).
    id: str
    invoice_id: str
    contributor_id: str
    entry_kind: str
    amount_cents: int
    posted_at: str
    created_at: str


class DeskConfig(TypedDict, total=False):
    id: str
    kill_fee_post_delivery_pct_num: int
    receipt_required_cents: int
    category_caps_cents: dict
    net_terms_days: int
    late_fee_daily_bps: int
    reporting_threshold_cents: int
    backup_withholding_rate_bps: int
    foreign_statutory_rate_bps: int
    treaty_rates_bps: dict
    flag_threshold_bps: int
    ai_flag_threshold_bps: int
    reuse_royalty_pct_num: int
    all_rights_uplift_pct_num: int
    created_at: str
    updated_at: str
    version: int
