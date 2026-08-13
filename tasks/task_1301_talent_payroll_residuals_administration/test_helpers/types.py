"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PAYROLL_ADMIN = "PayrollAdmin"
    PRODUCTION_ACCOUNTANT = "ProductionAccountant"
    PAYROLL_CLERK = "PayrollClerk"
    PAYROLL_SUPERVISOR = "PayrollSupervisor"
    UNION_AUDITOR = "UnionAuditor"


class UnionAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    RATIFIED = "RATIFIED"


class ProductionStatus(str, Enum):
    PRE_PRODUCTION = "PRE_PRODUCTION"
    SHOOTING = "SHOOTING"
    WRAPPED = "WRAPPED"
    ARCHIVED = "ARCHIVED"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    SUPERSEDED = "SUPERSEDED"
    WRAPPED = "WRAPPED"


class TimecardReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    FLAGGED = "FLAGGED"
    APPROVED = "APPROVED"


class TimecardPaymentStatus(str, Enum):
    UNBATCHED = "UNBATCHED"
    BATCHED = "BATCHED"
    PAID = "PAID"


class PenaltyAssessmentStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAIVED = "WAIVED"


class PenaltyType(str, Enum):
    MEAL = "MEAL"
    REST = "REST"
    TURNAROUND = "TURNAROUND"


class ResidualStatus(str, Enum):
    REPORTED = "REPORTED"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    BATCHED = "BATCHED"
    PAID = "PAID"


class ReuseMarket(str, Enum):
    NETWORK_REBROADCAST = "NETWORK_REBROADCAST"
    SYNDICATION = "SYNDICATION"
    STREAMING = "STREAMING"
    FOREIGN = "FOREIGN"
    HOME_VIDEO = "HOME_VIDEO"


class PayBatchStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"


class PayLineStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"


class PayLineSourceType(str, Enum):
    TIMECARD = "TIMECARD"
    RESIDUAL = "RESIDUAL"
    GRIEVANCE_ADJUSTMENT = "GRIEVANCE_ADJUSTMENT"


class GarnishmentOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class RemittanceReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


# --- Entity TypedDicts -------------------------------------------------------
# Resources carry id/created_at plus updated_at/version (PRD §2.4), except the
# two ledger entities PenaltyAssessment and PayLine, which carry only id and
# created_at.


class UnionAgreement(TypedDict, total=False):
    id: str
    union_code: str
    name: str
    effective_from: str
    effective_to: str
    rate_tiers: list
    meal_penalty_cents: int
    rest_penalty_cents: int
    turnaround_min_hours: float
    phw_pension_pct: float
    phw_health_pct: float
    phw_welfare_pct: float
    residual_base_pct_by_market: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class Production(TypedDict, total=False):
    id: str
    title: str
    production_company: str
    union_agreement_id: str
    production_type: str
    jurisdictions: list
    status: str
    created_at: str
    updated_at: str
    version: int


class Performer(TypedDict, total=False):
    id: str
    legal_name: str
    primary_union_code: str
    tax_residency_state: str
    ytd_gross_cents: int
    ytd_garnished_cents: int
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    production_id: str
    union_agreement_id: str
    performer_id: str
    tier_code: str
    payee_type: str
    loan_out_legal_name: Optional[str]
    loan_out_tax_id: Optional[str]
    weekly_guarantee_cents: int
    guaranteed_days: int
    start_date: str
    end_date: str
    supersedes_engagement_id: Optional[str]
    accrued_penalty_cents: int
    accrued_adjustment_cents: int
    ytd_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Timecard(TypedDict, total=False):
    id: str
    engagement_id: str
    work_date: str
    jurisdiction_code: str
    call_time: str
    first_meal_out: str
    first_meal_in: str
    wrap_time: str
    scheduled_hours: float
    worked_minutes: int
    overtime_minutes: int
    provisional_penalty_cents: int
    final_penalty_cents: int
    day_gross_cents: int
    review_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class PenaltyAssessment(TypedDict, total=False):
    # Immutable ledger row: id + created_at only; NO updated_at, NO version.
    id: str
    timecard_id: str
    penalty_type: str
    units: int
    amount_cents: int
    status: str
    created_at: str


class ResidualObligation(TypedDict, total=False):
    id: str
    engagement_id: str
    reuse_market: str
    window_start: str
    window_end: str
    reported_gross_receipts_cents: int
    base_pct: float
    window_sequence: int
    provisional_amount_cents: int
    final_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayBatch(TypedDict, total=False):
    id: str
    period_label: str
    cutoff_date: str
    created_by_user_id: str
    total_gross_cents: int
    total_tax_cents: int
    total_garnished_cents: int
    total_phw_cents: int
    total_net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PayLine(TypedDict, total=False):
    # Immutable ledger line: id + created_at only; NO updated_at, NO version.
    id: str
    pay_batch_id: str
    engagement_id: str
    source_type: str
    source_id: str
    gross_cents: int
    jurisdiction_code: str
    tax_cents: int
    garnished_cents: int
    phw_cents: int
    net_cents: int
    status: str
    created_at: str


class GarnishmentOrder(TypedDict, total=False):
    id: str
    performer_id: str
    creditor_name: str
    order_type: str
    priority_rank: int
    pct_of_disposable: Optional[float]
    fixed_amount_cents: Optional[int]
    total_withheld_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RemittanceReport(TypedDict, total=False):
    id: str
    pay_batch_id: str
    union_agreement_id: str
    pension_cents: int
    health_cents: int
    welfare_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrievanceCase(TypedDict, total=False):
    id: str
    engagement_id: str
    pay_line_id: Optional[str]
    filed_by_user_id: str
    category: str
    claimed_amount_cents: int
    awarded_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
