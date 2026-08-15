"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    VENDOR_SPECIALIST = "VendorSpecialist"
    VENDOR_MANAGER = "VendorManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AP_CLERK = "APClerk"
    AP_SUPERVISOR = "APSupervisor"
    AP_MANAGER = "APManager"
    CONTROLLER = "Controller"
    TREASURY_ANALYST = "TreasuryAnalyst"
    TREASURY_MANAGER = "TreasuryManager"
    BANK_FILE_PROCESSOR = "BankFileProcessor"
    AUDITOR = "Auditor"
    SYSTEM_ADMIN = "SystemAdmin"


class VendorStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DORMANT = "DORMANT"
    BLOCKED = "BLOCKED"
    REJECTED = "REJECTED"
    MERGED = "MERGED"
    DEACTIVATED = "DEACTIVATED"


class BankAccountStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    DISABLED = "DISABLED"


class CallbackStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    LOCKED = "LOCKED"
    EXPIRED = "EXPIRED"


class DocType(str, Enum):
    W9 = "W9"
    INSURANCE_CERT = "INSURANCE_CERT"
    BANK_AUTHORIZATION = "BANK_AUTHORIZATION"


class DocumentStatus(str, Enum):
    VALID = "VALID"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class WatchlistSeverity(str, Enum):
    BLOCK = "BLOCK"
    REVIEW = "REVIEW"


class WatchlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ScreeningSubjectType(str, Enum):
    VENDOR = "VENDOR"
    PAYMENT = "PAYMENT"


class ScreeningResult(str, Enum):
    CLEAR = "CLEAR"
    REVIEW = "REVIEW"
    HIT = "HIT"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    CONFIRMED_HIT = "CONFIRMED_HIT"


class CaseOpenedReason(str, Enum):
    SETUP_SCREENING = "SETUP_SCREENING"
    PAYMENT_SCREENING = "PAYMENT_SCREENING"


class InvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"
    IN_PAYMENT_RUN = "IN_PAYMENT_RUN"
    ON_HOLD = "ON_HOLD"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class MatrixRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PaymentRunStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPILED = "COMPILED"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    CLEARED = "CLEARED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    CHECK = "CHECK"
    ACH = "ACH"
    WIRE = "WIRE"


class VoidReason(str, Enum):
    MANUAL_REMOVED = "MANUAL_REMOVED"
    VENDOR_BLOCKED = "VENDOR_BLOCKED"
    POSITIVE_PAY_MISMATCH = "POSITIVE_PAY_MISMATCH"
    RUN_VOIDED = "RUN_VOIDED"


# --- Entity TypedDicts (documentation types; no runtime enforcement) ---
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
# ScreeningCheck, VendorMergeRecord and AuditEvent are append-only and carry
# only id + created_at; updated_at and version are absent on them (PRD §2.5).

class Vendor(TypedDict, total=False):
    id: str
    legal_name: str
    dba_name: Optional[str]
    tax_id: str
    remit_email: str
    phone: str
    address_line1: str
    city: str
    country: str
    payment_terms_days: int
    early_pay_discount_pct: float
    discount_window_days: int
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    first_activated_at: Optional[str]
    last_payment_cleared_at: Optional[str]
    dormant_since_at: Optional[str]
    duplicate_review_required: bool
    fraud_hold_reason: Optional[str]
    primary_bank_account_id: Optional[str]
    merged_into_vendor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorBankAccount(TypedDict, total=False):
    id: str
    vendor_id: str
    account_number: str
    routing_number: str
    account_holder_name: str
    is_primary: bool
    status: str
    requested_by_user_id: str
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CallbackVerification(TypedDict, total=False):
    id: str
    bank_account_id: str
    verification_code: str
    attempts: int
    status: str
    expires_at: str
    confirmed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorDocument(TypedDict, total=False):
    id: str
    vendor_id: str
    doc_type: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WatchlistEntry(TypedDict, total=False):
    id: str
    name_pattern: str
    severity: str
    list_source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningCheck(TypedDict, total=False):
    # Append-only: id + created_at only among common fields (no updated_at / version).
    id: str
    subject_type: str
    vendor_id: str
    payment_id: Optional[str]
    matched_watchlist_entry_id: Optional[str]
    match_score: float
    result: str
    screened_at: str
    created_at: str


class SanctionsReviewCase(TypedDict, total=False):
    id: str
    vendor_id: str
    payment_id: Optional[str]
    screening_check_id: str
    opened_reason: str
    status: str
    dispositioned_by_user_id: Optional[str]
    disposition_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    vendor_id: str
    invoice_number: str
    amount_cents: int
    cost_center: str
    received_date: str
    status: str
    pre_hold_status: Optional[str]
    required_tier: Optional[int]
    approval_round: int
    submitted_by_user_id: Optional[str]
    provisional_discount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InvoiceApproval(TypedDict, total=False):
    id: str
    invoice_id: str
    round_no: int
    tier: int
    approver_user_id: str
    approver_role: str
    created_at: str
    updated_at: str
    version: int


class ApprovalMatrixRule(TypedDict, total=False):
    id: str
    cost_center: str
    min_amount_cents: int
    max_amount_cents: Optional[int]
    tier: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentRun(TypedDict, total=False):
    id: str
    scheduled_date: str
    payment_method: str
    status: str
    total_amount_cents: int
    item_count: int
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    payment_run_id: str
    invoice_id: str
    vendor_id: str
    bank_account_id: str
    bank_account_version: int
    amount_cents: int
    discount_applied_cents: int
    fee_cents: int
    net_amount_cents: int
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorMergeRecord(TypedDict, total=False):
    # Append-only: id + created_at only among common fields (no updated_at / version).
    id: str
    survivor_vendor_id: str
    merged_vendor_id: str
    match_score: float
    invoices_repointed_count: int
    bank_accounts_disabled_count: int
    merged_by_user_id: str
    created_at: str


class AuditEvent(TypedDict, total=False):
    # Append-only: id + created_at only among common fields (no updated_at / version).
    id: str
    entity_type: str
    entity_id: str
    event_type: str
    field_name: Optional[str]
    old_value: Optional[str]
    new_value: Optional[str]
    actor_user_id: str
    actor_role: str
    created_at: str
