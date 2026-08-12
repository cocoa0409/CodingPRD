"""Domain types derived from the PRD entity model."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enumerations (statuses and policy enums used across the PRD)
# ---------------------------------------------------------------------------


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    TERMINATED = "TERMINATED"


class DayCountConvention(str, Enum):
    THIRTY_360 = "THIRTY_360"
    ACT_360 = "ACT_360"


class SubstantiationStandard(str, Enum):
    FULL_DOCUMENTATION = "FULL_DOCUMENTATION"
    SELF_CERTIFY = "SELF_CERTIFY"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ContributionStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ContributionElectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class LoanLifecycleStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    DISBURSED = "DISBURSED"
    REPAID = "REPAID"
    REFINANCED = "REFINANCED"
    OFFSET = "OFFSET"


class LoanDelinquencyStatus(str, Enum):
    NONE = "NONE"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEEMED = "DEEMED"


class InstallmentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    MISSED = "MISSED"
    CURED = "CURED"
    REBUILT = "REBUILT"
    CLOSED = "CLOSED"


class RemittanceStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class HardshipReason(str, Enum):
    MEDICAL = "MEDICAL"
    FUNERAL = "FUNERAL"
    EVICTION = "EVICTION"
    TUITION = "TUITION"
    HOME_PURCHASE = "HOME_PURCHASE"
    DISASTER = "DISASTER"


class HardshipStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDING_DOCUMENTS = "PENDING_DOCUMENTS"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PAID = "PAID"
    WITHDRAWN = "WITHDRAWN"


class HardshipDocumentType(str, Enum):
    INVOICE = "INVOICE"
    MEDICAL_BILL = "MEDICAL_BILL"
    BANK_STATEMENT = "BANK_STATEMENT"
    ATTESTATION = "ATTESTATION"
    EVICTION_NOTICE = "EVICTION_NOTICE"
    OTHER = "OTHER"


class ApprovalSubjectType(str, Enum):
    LOAN = "LOAN"
    HARDSHIP = "HARDSHIP"


class ApproverRole(str, Enum):
    PLAN_SPONSOR = "PLAN_SPONSOR"
    RECORDKEEPER_ADMIN = "RECORDKEEPER_ADMIN"


class ApprovalTaskStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DOCS_REQUESTED = "DOCS_REQUESTED"
    CANCELLED = "CANCELLED"


class SuspensionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class TaxEventSourceType(str, Enum):
    LOAN_DEEMED = "LOAN_DEEMED"
    LOAN_OFFSET = "LOAN_OFFSET"
    HARDSHIP_DISTRIBUTION = "HARDSHIP_DISTRIBUTION"


class TaxEventStatus(str, Enum):
    PENDING = "PENDING"
    REPORTED = "REPORTED"


class AmountSemantics(str, Enum):
    NET = "NET"
    GROSS = "GROSS"


class Decision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_DOCS = "REQUEST_DOCS"


class UserRole(str, Enum):
    Participant = "Participant"
    PlanSponsor = "PlanSponsor"
    RecordkeeperAdmin = "RecordkeeperAdmin"
    PayrollProvider = "PayrollProvider"
    Auditor = "Auditor"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Primary resources carry id + created_at + updated_at + version.
# Append-only resources (LoanInstallment, HardshipDocument, AuditEvent) carry
# only id + created_at.
# ---------------------------------------------------------------------------


class Plan(TypedDict, total=False):
    id: str
    name: str
    status: str
    max_loans_outstanding: int
    min_loan_amount_cents: int
    max_loan_amount_cents: int
    max_term_months: int
    interest_rate_bps: int
    day_count_convention: str
    allows_refinance: bool
    refinance_min_months_since_disbursement: int
    hardship_suspension_months: int
    substantiation_standard: str
    withholding_rate_bps: int
    allowed_hardship_reasons: list
    loan_approval_chain: list
    hardship_approval_chain: list
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    plan_id: str
    full_name: str
    external_ref: Optional[str]
    vested_balance_cents: int
    employment_status: str
    terminated_on: Optional[str]
    contribution_status: str
    ytd_taxable_distributions_cents: int
    loan_eligibility_locked_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContributionElection(TypedDict, total=False):
    id: str
    participant_id: str
    deferral_pct: float
    status: str
    effective_on: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    participant_id: str
    plan_id: str
    refinances_loan_id: Optional[str]
    principal_amount_cents: int
    term_months: int
    interest_rate_bps: int
    day_count_convention: str
    scheduled_payment_cents: Optional[int]
    outstanding_principal_cents: int
    accrued_unpaid_interest_cents: int
    lifecycle_status: str
    delinquency_status: str
    disbursed_on: Optional[str]
    cure_deadline_on: Optional[str]
    deemed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LoanInstallment(TypedDict, total=False):
    id: str
    loan_id: str
    installment_number: int
    due_date: str
    scheduled_amount_cents: int
    principal_portion_cents: int
    interest_portion_cents: int
    paid_amount_cents: int
    status: str
    created_at: str
    # NOTE: append-only — no updated_at, no version (PRD §2.4)


class PayrollRemittance(TypedDict, total=False):
    id: str
    participant_id: str
    amount_cents: int
    pay_date: str
    allocations: Optional[list]
    applied_allocations: list
    status: str
    created_at: str
    updated_at: str
    version: int


class HardshipRequest(TypedDict, total=False):
    id: str
    participant_id: str
    plan_id: str
    reason_category: str
    amount_cents: int
    amount_semantics: str
    attestation: Optional[bool]
    gross_withdrawal_cents: int
    withholding_cents: int
    fee_cents: int
    net_disbursed_cents: int
    status: str
    paid_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HardshipDocument(TypedDict, total=False):
    id: str
    hardship_request_id: str
    document_type: str
    amount_cents: int
    description: Optional[str]
    retained_until: Optional[str]
    created_at: str
    # NOTE: append-only — no updated_at, no version (PRD §2.4)


class ApprovalTask(TypedDict, total=False):
    id: str
    plan_id: str
    subject_type: str
    subject_id: str
    step_order: int
    approver_role: str
    status: str
    decided_by: Optional[str]
    decided_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SuspensionRecord(TypedDict, total=False):
    id: str
    participant_id: str
    hardship_request_id: str
    starts_on: str
    ends_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxEvent(TypedDict, total=False):
    id: str
    participant_id: str
    source_type: str
    source_id: str
    taxable_amount_cents: int
    event_date: str
    tax_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    id: str
    plan_id: str
    actor_role: str
    actor_id: str
    action: str
    subject_type: str
    subject_id: str
    detail: dict
    created_at: str
    # NOTE: append-only — no updated_at, no version (PRD §2.4)
