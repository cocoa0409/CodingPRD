"""Domain types: entity shapes, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    PROJECT_LEAD = "ProjectLead"
    PROGRAM_OFFICER = "ProgramOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    SPONSOR_ADMIN = "SponsorAdmin"
    DONOR = "Donor"


# ---------------------------------------------------------------------------
# Status enums (PRD §3 state narratives)
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SPUN_OFF = "SPUN_OFF"
    TERMINATED = "TERMINATED"


class AgreementStatus(str, Enum):
    PENDING_COUNTERSIGN = "PENDING_COUNTERSIGN"
    ACTIVE = "ACTIVE"
    SUPERSEDED_BY_INDEPENDENCE = "SUPERSEDED_BY_INDEPENDENCE"
    TERMINATED = "TERMINATED"


class FundStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class DonationStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    RECEIPTED = "RECEIPTED"
    REFUND_REQUESTED = "REFUND_REQUESTED"
    REFUNDED = "REFUNDED"


class ReceiptStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class DisbursementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PENDING_SPONSOR = "PENDING_SPONSOR"
    APPROVED_FOR_PAYMENT = "APPROVED_FOR_PAYMENT"
    PAID = "PAID"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class EngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VETTED = "VETTED"
    ACTIVE = "ACTIVE"
    CLASSIFICATION_REVIEW = "CLASSIFICATION_REVIEW"
    TERMINATED = "TERMINATED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    REMEDIATED = "REMEDIATED"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ExitPlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    DUE_DILIGENCE = "DUE_DILIGENCE"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class TrancheStatus(str, Enum):
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class FeeAssessmentStatus(str, Enum):
    FINAL = "FINAL"


class LedgerEntryType(str, Enum):
    DONATION_CREDIT = "DONATION_CREDIT"
    FEE_DEBIT = "FEE_DEBIT"
    DONATION_REFUND_DEBIT = "DONATION_REFUND_DEBIT"
    FEE_REVERSAL_CREDIT = "FEE_REVERSAL_CREDIT"
    COMMITMENT_HOLD = "COMMITMENT_HOLD"
    COMMITMENT_RELEASE = "COMMITMENT_RELEASE"
    DISBURSEMENT_DEBIT = "DISBURSEMENT_DEBIT"
    ADJUSTMENT = "ADJUSTMENT"
    RESERVE_HOLD = "RESERVE_HOLD"
    EXIT_TRANSFER_DEBIT = "EXIT_TRANSFER_DEBIT"


class SponsorshipModel(str, Enum):
    COMPREHENSIVE = "COMPREHENSIVE"
    PRE_APPROVED_GRANT = "PRE_APPROVED_GRANT"


class SpendingBasis(str, Enum):
    SETTLED = "SETTLED"
    FORWARD_LOOKING = "FORWARD_LOOKING"


class OversightPosture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    SEVERE = "SEVERE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.5 common properties; ledger entries exempt)
# ---------------------------------------------------------------------------
class ProjectApplication(TypedDict, total=False):
    id: str
    applicant_user_id: str
    project_name: str
    mission_statement: str
    requested_model: str
    budget_estimate_cents: int
    contact_email: str
    status: str
    purpose_pts: float
    benefit_pts: float
    capacity_pts: float
    risk_pts: float
    mission_score: Optional[float]
    review_note: Optional[str]
    decided_model: Optional[str]
    submit_count: int
    project_id: Optional[str]
    agreement_id: Optional[str]
    fund_account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    source_application_id: str
    name: str
    mission_statement: str
    lead_user_id: str
    status: str
    risk_score: int
    oversight_posture: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SponsorshipAgreement(TypedDict, total=False):
    id: str
    project_id: str
    model: str
    status: str
    spending_basis: str
    amendment_note: Optional[str]
    effective_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundAccount(TypedDict, total=False):
    id: str
    project_id: str
    status: str
    currency: str
    total_received_cents: int
    total_refunded_cents: int
    total_fees_charged_cents: int
    total_fees_reversed_cents: int
    total_disbursed_cents: int
    total_adjustments_cents: int
    total_transferred_out_cents: int
    committed_cents: int
    reserved_cents: int
    available_cents: int
    forward_available_cents: int
    created_at: str
    updated_at: str
    version: int


class FundLedgerEntry(TypedDict, total=False):
    # Append-only (PRD §2.5): carries ONLY id and created_at — no updated_at, no version.
    id: str
    created_at: str
    fund_account_id: str
    entry_type: str
    amount_cents: int
    donation_id: Optional[str]
    disbursement_id: Optional[str]
    memo: str


class Donation(TypedDict, total=False):
    id: str
    project_id: str
    fund_account_id: str
    amount_cents: int
    donor_name: str
    donor_email: str
    donor_tax_id: Optional[str]
    anonymous: bool
    payment_method: str
    status: str
    fee_cents: int
    refunded_cents: int
    pending_refund_amount_cents: Optional[int]
    status_before_refund: Optional[str]
    received_at: Optional[str]
    refunded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxReceipt(TypedDict, total=False):
    id: str
    donation_id: str
    receipt_number: str
    tax_year: int
    amount_cents: int
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisbursementRequest(TypedDict, total=False):
    id: str
    project_id: str
    fund_account_id: str
    staff_engagement_id: Optional[str]
    grant_tranche_id: Optional[str]
    amount_cents: int
    purpose: str
    payee_type: str
    payee_name: str
    spend_date: str
    status: str
    high_value: bool
    exit_settled: bool
    auto_reject_reason: Optional[str]
    submitted_by_user_id: Optional[str]
    compliance_approved_by_user_id: Optional[str]
    sponsor_approved_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffEngagement(TypedDict, total=False):
    id: str
    project_id: str
    worker_name: str
    worker_email: str
    engagement_type: str
    classification_overridden: bool
    compensation_type: str
    rate_cents: int
    start_date: str
    end_date: Optional[str]
    status: str
    contractor_ytd_cents: int
    ytd_year: Optional[int]
    requires_1099: bool
    created_at: str
    updated_at: str
    version: int


class ComplianceReview(TypedDict, total=False):
    id: str
    project_id: str
    review_type: str
    status: str
    findings_count: int
    open_findings_count: int
    severity_max: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskIncident(TypedDict, total=False):
    id: str
    project_id: str
    category: str
    severity: str
    description: str
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExitPlan(TypedDict, total=False):
    id: str
    project_id: str
    successor_entity_name: str
    successor_ein: str
    reason: str
    status: str
    signoffs: List[dict]
    committed_payout_cents: int
    reserve_cents: int
    exit_fee_cents: int
    transfer_cents: int
    created_at: str
    updated_at: str
    version: int


class GrantTranche(TypedDict, total=False):
    id: str
    agreement_id: str
    amount_cents: int
    period_start: str
    period_end: str
    purpose: str
    status: str
    committed_cents: int
    spent_cents: int
    report_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeeAssessment(TypedDict, total=False):
    id: str
    fund_account_id: str
    period_start: str
    period_end: str
    status: str
    provisional_fees_cents: int
    refund_reversals_cents: int
    annual_platform_fee_cents: int
    final_fees_cents: int
    delta_cents: int
    created_at: str
    updated_at: str
    version: int
