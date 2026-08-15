"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3, §4)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ACO_ADMINISTRATOR = "AcoAdministrator"
    CLAIMS_PROCESSOR = "ClaimsProcessor"
    QUALITY_REPORTER = "QualityReporter"
    QUALITY_AUDITOR = "QualityAuditor"
    SETTLEMENT_ACTUARY = "SettlementActuary"
    DISTRIBUTION_APPROVER = "DistributionApprover"
    MEDICAL_REVIEW_OFFICER = "MedicalReviewOfficer"
    APPEALS_OFFICER = "AppealsOfficer"
    PARTICIPANT_REPRESENTATIVE = "ParticipantRepresentative"
    PLATFORM_ADMIN = "PlatformAdmin"


class AgreementPeriodStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    ASSIGNMENT_LOCKED = "ASSIGNMENT_LOCKED"
    SETTLED = "SETTLED"


class Track(str, Enum):
    ONE_SIDED = "ONE_SIDED"
    TWO_SIDED = "TWO_SIDED"


class AlignmentMethodology(str, Enum):
    PROSPECTIVE = "PROSPECTIVE"
    RETROSPECTIVE = "RETROSPECTIVE"


class AlignmentRunStatus(str, Enum):
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    LOCKED = "LOCKED"


class AttributionRecordStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    UNDER_APPEAL = "UNDER_APPEAL"
    OVERTURNED = "OVERTURNED"
    EXCLUDED_OPT_OUT = "EXCLUDED_OPT_OUT"
    SUPERSEDED = "SUPERSEDED"


class ClaimType(str, Enum):
    PART_A = "PART_A"
    PART_B = "PART_B"


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ADJUDICATED = "ADJUDICATED"
    VOIDED = "VOIDED"


class BenchmarkVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class BenchmarkStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    LOCKED = "LOCKED"


class QualityScoreStatus(str, Enum):
    REPORTED = "REPORTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class SettlementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"
    FINAL = "FINAL"
    SETTLED = "SETTLED"
    REOPENED = "REOPENED"


class DistributionLineStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class HighCostReviewStatus(str, Enum):
    FLAGGED = "FLAGGED"
    CONFIRMED_EXCLUSION = "CONFIRMED_EXCLUSION"
    DISMISSED = "DISMISSED"


class DismissalReason(str, Enum):
    MANUAL = "MANUAL"
    THRESHOLD_FALLEN = "THRESHOLD_FALLEN"


class AppealSubjectType(str, Enum):
    ATTRIBUTION = "ATTRIBUTION"
    SETTLEMENT = "SETTLEMENT"


class AppealStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    REBUTTAL = "REBUTTAL"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class ElectionDirection(str, Enum):
    OPT_OUT = "OPT_OUT"
    OPT_IN = "OPT_IN"


class AdjustmentDirection(str, Enum):
    CREDIT = "CREDIT"
    DEBIT = "DEBIT"


class AdjustmentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class AgreementPeriod(TypedDict, total=False):
    id: str
    aco_tax_id: str
    aco_name: str
    performance_start_date: str
    performance_end_date: str
    track: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    agreement_period_id: str
    tin: str
    legal_name: str
    share_weight_bp: int
    created_at: str
    updated_at: str
    version: int


class Beneficiary(TypedDict, total=False):
    id: str
    medicare_id: str
    birth_year: int
    dual_eligible: bool
    disabled: bool
    esrd: bool
    created_at: str
    updated_at: str
    version: int


class DataSharingElection(TypedDict, total=False):
    # Append-only event log entry: carries only id + created_at (PRD §2.4).
    id: str
    beneficiary_id: str
    direction: str
    effective_date: str
    created_at: str


class AlignmentRun(TypedDict, total=False):
    id: str
    agreement_period_id: str
    methodology: str
    window_start_date: str
    window_end_date: str
    records_created_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AttributionRecord(TypedDict, total=False):
    id: str
    agreement_period_id: str
    beneficiary_id: str
    alignment_run_id: str
    participant_id: str
    plurality_cost_cents: int
    methodology: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    id: str
    agreement_period_id: str
    beneficiary_id: str
    participant_id: Optional[str]
    service_date: str
    allowed_amount_cents: int
    claim_type: str
    review_excluded: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Benchmark(TypedDict, total=False):
    id: str
    agreement_period_id: str
    variant: str
    beneficiary_months: int
    risk_score_sum: float
    update_factor_used: float
    total_benchmark_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityScore(TypedDict, total=False):
    id: str
    agreement_period_id: str
    measure_code: str
    numerator: int
    denominator: int
    max_points: int
    performance_rate: float
    earned_points: float
    reported_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    agreement_period_id: str
    benchmark_id: str
    expenditure_total_cents: int
    gross_savings_cents: int
    msr_threshold_cents: int
    quality_score_snapshot: float
    quality_multiplier_snapshot: float
    shared_savings_pre_sequestration_cents: int
    sequestration_levy_cents: int
    net_shared_savings_cents: int
    shared_loss_cents: int
    distributable_pool_cents: int
    reconciliation_balance_cents: int
    last_distribution_run_by_user_id: Optional[str]
    finalized_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionLine(TypedDict, total=False):
    id: str
    settlement_id: str
    participant_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HighCostReview(TypedDict, total=False):
    id: str
    agreement_period_id: str
    beneficiary_id: str
    flagged_expenditure_cents: int
    dismissal_reason: Optional[str]
    determined_by_user_id: Optional[str]
    rationale: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    agreement_period_id: str
    subject_type: str
    subject_id: str
    filed_by_participant_id: str
    grounds: str
    round_count: int
    decided_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReconciliationAdjustment(TypedDict, total=False):
    id: str
    settlement_id: str
    appeal_id: Optional[str]
    direction: str
    amount_cents: int
    reason_code: str
    status: str
    created_at: str
    updated_at: str
    version: int
