"""Domain types: entity TypedDicts, status enums, role enum (PRD §2-§4)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    COMP_ANALYST = "CompAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COMP_COMMITTEE = "CompCommittee"
    PHYSICIAN = "Physician"


class ProviderType(str, Enum):
    PHYSICIAN = "PHYSICIAN"
    APP = "APP"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    FMV_APPROVED = "FMV_APPROVED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CLOSED = "CLOSED"


class AttributionMode(str, Enum):
    SERVICE_DATE = "SERVICE_DATE"
    POSTING_DATE = "POSTING_DATE"


class QualityModel(str, Enum):
    ALL_OR_NOTHING = "ALL_OR_NOTHING"
    SLIDING_SCALE = "SLIDING_SCALE"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_FMV = "PENDING_FMV"
    FMV_APPROVED = "FMV_APPROVED"
    EFFECTIVE = "EFFECTIVE"
    AMENDMENT_REQUIRED = "AMENDMENT_REQUIRED"
    TERMINATED = "TERMINATED"


class CaptureStatus(str, Enum):
    POSTED = "POSTED"
    VALIDATED = "VALIDATED"
    LOCKED = "LOCKED"
    VOIDED = "VOIDED"


class CreditStatus(str, Enum):
    UNCREDITED = "UNCREDITED"
    CREDITED = "CREDITED"
    REVERSED = "REVERSED"


class CaptureKind(str, Enum):
    CLINICAL = "CLINICAL"
    SUPERVISION_CREDIT = "SUPERVISION_CREDIT"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class ScorecardStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class TrueUpStatus(str, Enum):
    COMPUTED = "COMPUTED"
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DATA_CORRECTION = "DATA_CORRECTION"
    RESOLVED_ACCEPTED = "RESOLVED_ACCEPTED"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"


class SubjectType(str, Enum):
    CAPTURE = "CAPTURE"
    STATEMENT = "STATEMENT"


class DisputeResolution(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PcrStatus(str, Enum):
    PROPOSED = "PROPOSED"
    MODELED = "MODELED"
    COMMUNICATED = "COMMUNICATED"
    EFFECTIVE = "EFFECTIVE"
    WITHDRAWN = "WITHDRAWN"


class Tier(TypedDict):
    tier_code: str
    threshold_wrvu: float
    conversion_factor_cents: int
    tier_bonus_cents: int


class Measure(TypedDict):
    measure_code: str
    weight: int
    threshold_score: float
    score: float


# All resources carry the four common properties of PRD §2.5:
# id, created_at, updated_at, version.


class Physician(TypedDict):
    id: str
    npi: str
    full_name: str
    specialty: str
    provider_type: str
    fte: float
    hire_date: str
    created_at: str
    updated_at: str
    version: int


class CompPlan(TypedDict):
    id: str
    name: str
    fiscal_year_start: str
    fiscal_year_end: str
    credit_attribution_mode: str
    quality_model: str
    tiers: List[Tier]
    quality_pool_cents: int
    fmv_cap_cents: int
    supersedes_plan_id: Optional[str]
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CptRate(TypedDict):
    id: str
    plan_id: str
    cpt_code: str
    wrvu_value: float
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class PhysicianAgreement(TypedDict):
    id: str
    physician_id: str
    plan_id: str
    pinned_plan_version: int
    base_salary_cents: int
    period_draw_cents: int
    effective_date: str
    status: str
    fmv_reviewed_at: Optional[str]
    fmv_reviewer_user_id: Optional[str]
    fmv_benchmark_percentile: Optional[int]
    last_fmv_rejected_at: Optional[str]
    created_by_user_id: str
    compliance_hold: bool
    ytd_wrvu_credited: float
    lifetime_paid_cents: int
    pending_trueup_adjustment_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductionCapture(TypedDict):
    id: str
    agreement_id: str
    capture_kind: str
    cpt_code: str
    units: int
    service_date: str
    posting_date: str
    wrvu_value_applied: Optional[float]
    credited_wrvu: Optional[float]
    credited_period: Optional[str]
    capture_status: str
    credit_status: str
    reversal_of_capture_id: Optional[str]
    source_capture_id: Optional[str]
    reversed_reason: Optional[str]
    created_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupervisionAssignment(TypedDict):
    id: str
    supervisor_physician_id: str
    app_physician_id: str
    start_date: str
    end_date: str
    credit_pct: float
    supervised_fte: float
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityScorecard(TypedDict):
    id: str
    agreement_id: str
    period: str
    measures: List[Measure]
    quality_bonus_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CompStatement(TypedDict):
    id: str
    agreement_id: str
    period_year: int
    period_month: int
    capture_ids: List[str]
    period_wrvu: float
    ytd_wrvu_at_close: float
    tier_attained: str
    tier_bonus_cents: int
    productivity_earned_ytd_cents: int
    period_productivity_cents: int
    quality_bonus_cents: int
    period_draw_cents: int
    trueup_adjustment_cents: int
    net_payment_cents: int
    status: str
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class TrueUpAdjustment(TypedDict):
    agreement_id: str
    variance_cents: int


class TrueUpRun(TypedDict):
    id: str
    plan_id: str
    as_of_period: str
    adjustments: List[TrueUpAdjustment]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    filer_physician_id: str
    agreement_id: str
    subject_type: str
    subject_capture_id: Optional[str]
    subject_statement_id: Optional[str]
    reason: str
    corrected_units: Optional[int]
    corrected_cpt_code: Optional[str]
    status: str
    resolution: Optional[str]
    resolver_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlanChangeRequest(TypedDict):
    id: str
    plan_id: str
    successor_plan_id: str
    effective_date: str
    summary: str
    status: str
    modeled_delta_cents: Optional[int]
    acknowledged_physician_ids: List[str]
    created_at: str
    updated_at: str
    version: int
