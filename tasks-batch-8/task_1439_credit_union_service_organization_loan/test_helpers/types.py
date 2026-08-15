"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class CreditUnionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CusoStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class InvestmentStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class OfferingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class CertificateStatus(str, Enum):
    PENDING_DILIGENCE = "PENDING_DILIGENCE"
    COMMITTED = "COMMITTED"
    ACTIVE = "ACTIVE"
    EXCEPTION = "EXCEPTION"
    PAID_OFF = "PAID_OFF"
    DECLINED = "DECLINED"
    RESCINDED = "RESCINDED"
    REPURCHASED = "REPURCHASED"


class ExceptionStatus(str, Enum):
    OPEN = "OPEN"
    CURE_SUBMITTED = "CURE_SUBMITTED"
    REJECTED = "REJECTED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"


class RemittanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    PAID_LATE = "PAID_LATE"
    LATE_UNPAID = "LATE_UNPAID"
    REVERSED = "REVERSED"


class SurveillanceReportStatus(str, Enum):
    CURRENT = "CURRENT"
    SUPERSEDED = "SUPERSEDED"


class ExamStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    FINALIZED = "FINALIZED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    VERIFYING = "VERIFYING"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class LossEventStatus(str, Enum):
    REPORTED = "REPORTED"
    ALLOCATED = "ALLOCATED"


class RepurchaseCaseStatus(str, Enum):
    TRIGGERED = "TRIGGERED"
    DISPUTED = "DISPUTED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    TREASURY_USER = "TreasuryUser"
    REGULATOR_USER = "RegulatorUser"
    CUSO_OFFICER = "CUSOOfficer"
    ORIGINATOR_USER = "OriginatorUser"
    BUYER_USER = "BuyerUser"


class CreditUnion(TypedDict, total=False):
    id: str
    charter_number: str
    legal_name: str
    cu_type: str
    total_assets_cents: int
    net_worth_cents: int
    concentration_cap_pct: float
    status: str
    net_worth_ratio: float
    total_committed_principal_cents: int
    created_at: str
    updated_at: str
    version: int


class CUSO(TypedDict, total=False):
    id: str
    legal_name: str
    service_line: str
    status: str
    total_approved_investment_cents: int
    open_critical_finding_count: int
    created_at: str
    updated_at: str
    version: int


class CUSOInvestment(TypedDict, total=False):
    id: str
    credit_union_id: str
    cuso_id: str
    amount_cents: int
    approval_basis: str
    status: str
    post_approval_aggregate_cents: int
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServicingAgreement(TypedDict, total=False):
    id: str
    cuso_id: str
    originator_id: str
    servicing_fee_bps: int
    remittance_due_day: int
    grace_period_days: int
    cure_period_days: int
    day_count_convention: str
    late_remittance_threshold: int
    late_remittance_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ParticipationOffering(TypedDict, total=False):
    id: str
    servicing_agreement_id: str
    pool_name: str
    pool_principal_cents: int
    min_share_pct: float
    yield_rate_bps: int
    loss_basis: str
    open_at: str
    close_at: str
    status: str
    committed_principal_cents: int
    remaining_principal_cents: int
    created_at: str
    updated_at: str
    version: int


class ParticipationCertificate(TypedDict, total=False):
    id: str
    offering_id: str
    buyer_id: str
    committed_amount_cents: int
    share_pct: float
    status: str
    funded_amount_cents: int
    outstanding_principal_cents: int
    cumulative_interest_cents: int
    cumulative_loss_cents: int
    diligence_decision_at: Optional[str]
    funded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocumentationException(TypedDict, total=False):
    id: str
    certificate_id: str
    exception_type: str
    description: str
    detected_at: str
    cure_deadline: str
    status: str
    cure_notes: Optional[str]
    cure_attempt_count: int
    created_at: str
    updated_at: str
    version: int


class Remittance(TypedDict, total=False):
    id: str
    certificate_id: str
    period_start: str
    period_end: str
    collections_cents: int
    due_at: str
    interest_portion_cents: int
    servicing_fee_cents: int
    principal_portion_cents: int
    penalty_cents: int
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurveillanceReport(TypedDict, total=False):
    id: str
    servicing_agreement_id: str
    period_start: str
    period_end: str
    weighting_basis: str
    status: str
    total_outstanding_principal_cents: int
    active_certificate_count: int
    weighted_avg_yield_bps: int
    delinquent_remittance_count: int
    created_at: str
    updated_at: str
    version: int


class RegulatoryExam(TypedDict, total=False):
    id: str
    cuso_id: str
    start_date: str
    end_date: str
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExamFinding(TypedDict, total=False):
    id: str
    exam_id: str
    severity: str
    description: str
    remediation_due_date: str
    recorded_by_user_id: str
    status: str
    remediation_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LossEvent(TypedDict, total=False):
    id: str
    offering_id: str
    loss_amount_cents: int
    defaulted_at: str
    loss_basis_used: str
    allocations: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class RepurchaseCase(TypedDict, total=False):
    id: str
    certificate_id: str
    trigger_reason: str
    documentation_exception_id: Optional[str]
    repurchase_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
