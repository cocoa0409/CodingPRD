"""Domain types: entity TypedDicts, status enums, role enum.

Field names follow the PRD exactly. InvoiceLine and SpendLedgerEntry are
append-only kinds: they carry only `id` and `created_at` (no `updated_at`,
no `version`).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    HIRING_MANAGER = "HiringManager"
    SUPPLIER_COORDINATOR = "SupplierCoordinator"
    WORKER = "Worker"
    FINANCE_ANALYST = "FinanceAnalyst"
    ANONYMOUS = "Anonymous"


class SupplierTier(str, Enum):
    PREFERRED = "PREFERRED"
    APPROVED = "APPROVED"
    PROBATION = "PROBATION"


class SupplierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RateCardStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EngagementType(str, Enum):
    REQUISITION = "REQUISITION"
    SOW = "SOW"


class PaymentBasis(str, Enum):
    HOURLY = "HOURLY"
    FIXED = "FIXED"


class SupervisionLevel(str, Enum):
    DAILY = "DAILY"
    MILESTONE = "MILESTONE"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    OPEN = "OPEN"
    FILLING = "FILLING"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class MisclassificationRisk(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class OfferStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CONSUMED = "CONSUMED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class OfferAction(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"


class WorkerStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    OFFBOARDING = "OFFBOARDING"
    EXITED = "EXITED"


class ConversionStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CONVERTED = "CONVERTED"
    DECLINED = "DECLINED"


class AssignmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class TerminationReason(str, Enum):
    MANUAL = "MANUAL"
    ENGAGEMENT_CLOSED = "ENGAGEMENT_CLOSED"
    CONVERTED = "CONVERTED"


class TimesheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class MilestoneAcceptanceStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class MilestonePaymentStatus(str, Enum):
    UNINVOICED = "UNINVOICED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class FeeVariant(str, Enum):
    SCHEDULE = "SCHEDULE"
    PRORATA = "PRORATA"


class ConversionRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class AuditFinding(str, Enum):
    OVER_RATE = "OVER_RATE"
    MARKUP_EXCEEDED = "MARKUP_EXCEEDED"
    TENURE_RISK = "TENURE_RISK"
    BUDGET_UTILIZATION = "BUDGET_UTILIZATION"


class AuditSeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class LedgerEntryType(str, Enum):
    TIMESHEET_APPROVED = "TIMESHEET_APPROVED"
    TIMESHEET_VOIDED = "TIMESHEET_VOIDED"
    MILESTONE_ACCEPTED = "MILESTONE_ACCEPTED"


# --- Entity TypedDicts (common_fields: true unless noted) ---


class Supplier(TypedDict):
    id: str
    name: str
    supplier_code: str
    tier: str
    status: str
    tier_score: Optional[int]
    offers_made_count: int
    offers_filled_count: int
    open_offers_count: int
    completed_assignments_count: int
    open_violation_count: int
    milestones_delivered_count: int
    milestones_accepted_count: int
    spend_ytd_cents: int
    created_at: str
    updated_at: str
    version: int


class RateCard(TypedDict):
    id: str
    role_code: str
    skill_code: str
    geo_code: str
    currency: str
    pay_rate_floor_cents: int
    bill_rate_ceiling_cents: int
    max_markup_pct: float
    effective_from: str
    effective_to: str
    status: str
    supersedes_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict):
    id: str
    title: str
    engagement_type: str
    role_code: str
    skill_code: str
    geo_code: str
    payment_basis: str
    supervision_level: str
    duration_months: int
    budget_cents: int
    prorata_conversion: bool
    status: str
    misclassification_risk: Optional[str]
    classification_note: Optional[str]
    awarded_supplier_id: Optional[str]
    committed_spend_cents: int
    budget_audit_raised: bool
    created_at: str
    updated_at: str
    version: int


class DistributionOffer(TypedDict):
    id: str
    engagement_id: str
    supplier_id: str
    status: str
    offered_at: str
    response_due_at: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict):
    id: str
    supplier_id: str
    full_name: str
    email: str
    tenure_carryover_days: int
    status: str
    conversion_status: str
    cumulative_tenure_days: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    worker_id: str
    engagement_id: str
    offer_id: str
    supplier_id: str
    rate_card_id: str
    bill_rate_cents: int
    pay_rate_cents: int
    start_date: str
    end_date: str
    actual_end_date: Optional[str]
    status: str
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Timesheet(TypedDict):
    id: str
    assignment_id: str
    period_start: str
    period_end: str
    submitted_hours: float
    approved_hours: Optional[float]
    status: str
    provisional_amount_cents: Optional[int]
    final_amount_cents: Optional[int]
    rejection_reason: Optional[str]
    void_reason: Optional[str]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Milestone(TypedDict):
    id: str
    engagement_id: str
    name: str
    amount_cents: int
    due_date: str
    acceptance_status: str
    payment_status: str
    rejection_reason: Optional[str]
    delivered_by_supplier_id: Optional[str]
    accepted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    supplier_id: str
    period_start: str
    period_end: str
    status: str
    line_count: int
    subtotal_cents: int
    processing_fee_cents: int
    total_cents: int
    consolidation_savings_cents: int
    finalized_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    """Append-only kind: carries ONLY id + created_at (no updated_at/version)."""

    id: str
    invoice_id: str
    timesheet_id: Optional[str]
    milestone_id: Optional[str]
    amount_cents: int
    created_at: str


class ConversionRequest(TypedDict):
    id: str
    worker_id: str
    assignment_id: str
    tenure_days_at_request: int
    fee_variant: str
    fee_cents: int
    status: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict):
    id: str
    supplier_id: str
    engagement_id: Optional[str]
    timesheet_id: Optional[str]
    assignment_id: Optional[str]
    finding: str
    severity: str
    status: str
    details: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpendLedgerEntry(TypedDict):
    """Append-only kind: carries ONLY id + created_at (no updated_at/version)."""

    id: str
    supplier_id: str
    engagement_id: str
    timesheet_id: Optional[str]
    milestone_id: Optional[str]
    invoice_id: Optional[str]
    entry_type: str
    delta_cents: int
    running_balance_cents: int
    created_at: str
