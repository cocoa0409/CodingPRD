"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (PRD §3 lifecycle narratives)
# ---------------------------------------------------------------------------

class ProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class GroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PracticeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class MemberStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    DISENROLLED = "DISENROLLED"


class SpanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    RENEWED = "RENEWED"


class YearStatus(str, Enum):
    SETUP = "SETUP"
    ATTRIBUTION_OPEN = "ATTRIBUTION_OPEN"
    ATTRIBUTION_LOCKED = "ATTRIBUTION_LOCKED"
    MEASURING = "MEASURING"
    RECONCILING = "RECONCILING"
    SETTLED = "SETTLED"
    CLOSED = "CLOSED"


class RunStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class RecordStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CONFIRMED = "CONFIRMED"
    EXCLUDED = "EXCLUDED"


class ScoreStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PAID = "PAID"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class ResultStatus(str, Enum):
    REPORTED = "REPORTED"
    VALIDATED = "VALIDATED"
    LOCKED = "LOCKED"
    EXCLUDED = "EXCLUDED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    STALE = "STALE"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    RECALCULATING = "RECALCULATING"
    AUTHORIZED = "AUTHORIZED"
    DISTRIBUTED = "DISTRIBUTED"
    VOID = "VOID"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERRULED = "OVERRULED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class RemittanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    RETURNED = "RETURNED"


class AnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETE = "COMPLETE"
    SUPERSEDED = "SUPERSEDED"


class RiskTrack(str, Enum):
    ONE_SIDED_UPSIDE = "ONE_SIDED_UPSIDE"
    TWO_SIDED = "TWO_SIDED"


class RiskModel(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    CONCURRENT = "CONCURRENT"


class EstimateMethod(str, Enum):
    ANNUALIZATION = "ANNUALIZATION"
    COMPLETION_FACTOR = "COMPLETION_FACTOR"


class LineOfBusiness(str, Enum):
    MEDICARE_ADVANTAGE = "MEDICARE_ADVANTAGE"
    MEDICAID_MANAGED_CARE = "MEDICAID_MANAGED_CARE"
    COMMERCIAL_ACO = "COMMERCIAL_ACO"


class Recommendation(str, Enum):
    RENEW_AS_IS = "RENEW_AS_IS"
    RENEW_RENEGOTIATE = "RENEW_RENEGOTIATE"
    DO_NOT_RENEW = "DO_NOT_RENEW"


class UserRole(str, Enum):
    """The eleven roles named in PRD §2.1."""
    PAYER_ADMIN = "PayerAdmin"
    CONTRACT_MANAGER = "ContractManager"
    ATTRIBUTION_ANALYST = "AttributionAnalyst"
    ACTUARY_ANALYST = "ActuaryAnalyst"
    QUALITY_ANALYST = "QualityAnalyst"
    CLAIMS_PROCESSOR = "ClaimsProcessor"
    SETTLEMENT_OFFICER = "SettlementOfficer"
    DISPUTE_ADJUDICATOR = "DisputeAdjudicator"
    PAYMENT_OPS = "PaymentOps"
    AUDITOR = "Auditor"
    PRACTICE_GROUP_REP = "PracticeGroupRep"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all entities carry the four common fields of PRD §2.5
# ---------------------------------------------------------------------------

class Program(TypedDict, total=False):
    id: str
    program_name: str
    line_of_business: str
    program_status: str
    created_at: str
    updated_at: str
    version: int


class PracticeGroup(TypedDict, total=False):
    id: str
    group_name: str
    tin: str
    group_status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Practice(TypedDict, total=False):
    id: str
    practice_group_id: str
    practice_name: str
    npi: str
    practice_status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    program_id: str
    member_ref: str
    birth_year: int
    member_status: str
    created_at: str
    updated_at: str
    version: int


class EligibilitySpan(TypedDict, total=False):
    id: str
    member_id: str
    start_date: str
    end_date: str
    span_status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    program_id: str
    practice_group_id: str
    contract_ref: str
    effective_start: str
    effective_end: str
    risk_track: str
    risk_model: str
    benchmark_pmpm_cents: int
    shared_savings_rate_bp: int
    shared_loss_rate_bp: Optional[int]
    min_savings_rate_bp: int
    min_loss_rate_bp: Optional[int]
    savings_cap_bp: int
    loss_cap_bp: Optional[int]
    stop_loss_cents: int
    withhold_rate_bp: int
    quality_gate_floor_points: int
    quality_gate_excellence_points: int
    estimate_method: str
    quality_measures: list
    renewed_from_contract_id: Optional[str]
    contract_status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceYear(TypedDict, total=False):
    id: str
    contract_id: str
    year_label: int
    period_start: str
    period_end: str
    year_status: str
    total_member_months: int
    actual_cost_cents: int
    benchmark_cost_cents: int
    risk_adjustment_factor_milli: Optional[int]
    withhold_pool_cents: int
    accrued_reserve_cents: int
    locked_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttributionRun(TypedDict, total=False):
    id: str
    performance_year_id: str
    run_label: str
    run_seq: int
    run_status: str
    attributed_member_count: int
    created_at: str
    updated_at: str
    version: int


class AttributionRecord(TypedDict, total=False):
    id: str
    attribution_run_id: str
    member_id: str
    practice_id: str
    member_months: int
    record_status: str
    created_at: str
    updated_at: str
    version: int


class RiskScore(TypedDict, total=False):
    id: str
    member_id: str
    performance_year_id: str
    model_used: str
    score_milli: int
    score_status: str
    created_at: str
    updated_at: str
    version: int


class ClaimRecord(TypedDict, total=False):
    id: str
    performance_year_id: str
    member_id: str
    claim_ref: str
    service_date: str
    paid_amount_cents: int
    claim_status: str
    paid_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityMeasureResult(TypedDict, total=False):
    id: str
    performance_year_id: str
    measure_code: str
    numerator_count: int
    denominator_count: int
    rate_bp: Optional[int]
    achievement_points: Optional[int]
    result_status: str
    created_at: str
    updated_at: str
    version: int


class InterimReport(TypedDict, total=False):
    id: str
    performance_year_id: str
    months_elapsed: int
    report_seq: int
    est_actual_annualization_cents: Optional[int]
    est_actual_completion_cents: Optional[int]
    est_net_payable_cents: Optional[int]
    reserve_accrual_cents: Optional[int]
    report_status: str
    published_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    performance_year_id: str
    settlement_seq: int
    settlement_status: str
    gross_savings_cents: Optional[int]
    savings_rate_bp: Optional[int]
    shared_savings_cents: int
    shared_losses_cents: int
    quality_composite_points: Optional[int]
    quality_multiplier_bp: Optional[int]
    quality_adjusted_savings_cents: int
    withhold_released_cents: int
    withhold_forfeited_cents: int
    net_payable_cents: Optional[int]
    undistributed_balance_cents: Optional[int]
    finalized_on: Optional[str]
    finalized_by_user_id: Optional[str]
    needs_recompute: bool
    created_at: str
    updated_at: str
    version: int


class SettlementDispute(TypedDict, total=False):
    id: str
    settlement_id: str
    dispute_ref: str
    reason_code: str
    claimed_adjustment_cents: int
    filed_on: str
    review_started_on: Optional[str]
    resolved_on: Optional[str]
    resolved_by_user_id: Optional[str]
    resolution_outcome: Optional[str]
    dispute_status: str
    created_at: str
    updated_at: str
    version: int


class DistributionRemittance(TypedDict, total=False):
    id: str
    settlement_id: str
    practice_id: str
    practice_member_months: int
    amount_cents: int
    remittance_status: str
    paid_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RenewalAnalysis(TypedDict, total=False):
    id: str
    contract_id: str
    analysis_seq: int
    realized_savings_rate_bp: Optional[int]
    quality_trend_points: Optional[int]
    risk_growth_milli: Optional[int]
    recommendation: Optional[str]
    analysis_status: str
    created_at: str
    updated_at: str
    version: int
