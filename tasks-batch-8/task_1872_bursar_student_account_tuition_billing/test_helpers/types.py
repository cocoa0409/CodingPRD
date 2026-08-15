"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (PRD §3 state machines)
# ---------------------------------------------------------------------------

class TermStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CENSUS_LOCKED = "CENSUS_LOCKED"
    CLOSED = "CLOSED"


class AccountStatus(str, Enum):
    OPEN = "OPEN"
    PAST_DUE = "PAST_DUE"
    COLLECTIONS = "COLLECTIONS"
    WRITTEN_OFF = "WRITTEN_OFF"
    CLOSED = "CLOSED"


class WriteoffStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    DROPPED = "DROPPED"
    WITHDRAWN = "WITHDRAWN"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class WaiverStatus(str, Enum):
    AWARDED = "AWARDED"
    POSTED = "POSTED"
    REVOKED = "REVOKED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    TERMINATED = "TERMINATED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAST_DUE = "PAST_DUE"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class RefundStatus(str, Enum):
    CALCULATED = "CALCULATED"
    POSTED = "POSTED"
    VOID = "VOID"


class TaxFormStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    STUDENT = "Student"
    REGISTRAR = "RegistrarStaff"
    BURSAR_STAFF = "BursarStaff"
    BURSAR_MANAGER = "BursarManager"


class LedgerEntryType(str, Enum):
    CHARGE = "CHARGE"
    CHARGE_REVERSAL = "CHARGE_REVERSAL"
    PAYMENT = "PAYMENT"
    PAYMENT_REVERSAL = "PAYMENT_REVERSAL"
    WAIVER = "WAIVER"
    WAIVER_REVERSAL = "WAIVER_REVERSAL"
    SPONSOR_CHARGE = "SPONSOR_CHARGE"
    SPONSOR_REVERSAL = "SPONSOR_REVERSAL"
    LATE_FEE = "LATE_FEE"
    PLAN_FEE = "PLAN_FEE"
    COLLECTIONS_FEE = "COLLECTIONS_FEE"
    WRITE_OFF = "WRITE_OFF"
    REFUND_PAYOUT = "REFUND_PAYOUT"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields entities carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------

class Term(TypedDict):
    id: str
    code: str
    name: str
    start_date: str
    end_date: str
    census_date: str
    full_refund_end_date: str
    mid_refund_end_date: str
    withdrawal_deadline: str
    refund_policy: str
    flat_fee_cents: int
    hold_threshold_cents: int
    plan_setup_fee_cents: int
    late_fee_pct: float
    grace_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    external_ref: str
    residency_status: str
    level: str
    created_at: str
    updated_at: str
    version: int


class TuitionRate(TypedDict):
    id: str
    term_id: str
    residency: str
    level: str
    per_credit_rate_cents: int
    full_time_threshold_credits: int
    flat_rate_cents: int
    max_flat_credits: int
    overload_rate_cents: int
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class StudentAccount(TypedDict):
    id: str
    student_id: str
    term_id: str
    status: str
    charges_total_cents: int
    payments_total_cents: int
    waivers_total_cents: int
    sponsor_total_cents: int
    writeoffs_total_cents: int
    balance_cents: int
    past_due_cents: int
    writeoff_status: str
    writeoff_requester_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict):
    # Append-only ledger: only id + created_at common fields (PRD §2.5) —
    # NO updated_at, NO version.
    id: str
    account_id: str
    entry_type: str
    charge_kind: Optional[str]
    amount_cents: int
    due_date: Optional[str]
    enrollment_id: Optional[str]
    source_ref: str
    memo: str
    created_at: str


class Enrollment(TypedDict):
    id: str
    student_id: str
    term_id: str
    account_id: str
    credit_hours: int
    effective_date: str
    status: str
    exit_date: Optional[str]
    assessed_total_cents: int
    created_at: str
    updated_at: str
    version: int


class PaymentAllocation(TypedDict):
    ledger_entry_id: str
    amount_cents: int


class Payment(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    method: str
    status: str
    allocations: List[PaymentAllocation]
    unapplied_cents: int
    reversed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    account_id: str
    kind: str
    awarded_cents: int
    posted_cents: int
    allocations: List[PaymentAllocation]
    status: str
    created_at: str
    updated_at: str
    version: int


class SponsorAgreement(TypedDict):
    id: str
    sponsor_name: str
    student_id: str
    term_id: str
    cap_cents: int
    covers_tuition: bool
    covers_fees: bool
    billing_basis: str
    start_date: str
    end_date: str
    billed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    ledger_entry_id: str
    memo: str
    amount_cents: int


class SponsorInvoice(TypedDict):
    id: str
    agreement_id: str
    invoice_date: str
    lines: List[InvoiceLine]
    total_cents: int
    paid_cents: int
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentPlan(TypedDict):
    id: str
    account_id: str
    installment_count: int
    first_due_date: str
    principal_cents: int
    fee_cents: int
    total_cents: int
    defaulted_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    plan_id: str
    sequence: int
    due_date: str
    amount_cents: int
    paid_cents: int
    late_fee_posted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancialHold(TypedDict):
    id: str
    account_id: str
    hold_type: str
    origin: str
    reason: str
    status: str
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    account_id: str
    enrollment_id: str
    trigger: str
    effective_date: str
    policy_variant: str
    basis_cents: int
    pct_applied: float
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxForm1098T(TypedDict):
    id: str
    student_id: str
    tax_year: int
    box1_cents: int
    box4_cents: int
    box5_cents: int
    status: str
    corrected_from_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
