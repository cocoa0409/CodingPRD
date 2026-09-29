"""Domain types for the Multiemployer Plan Withdrawal Liability API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them. Every resource kind in this system carries `id`, `created_at`,
`updated_at` and `version`, so every TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    FUND_ADMINISTRATOR = "FundAdministrator"
    PLAN_ACTUARY = "PlanActuary"
    PLAN_TRUSTEE = "PlanTrustee"
    EMPLOYER_REPRESENTATIVE = "EmployerRepresentative"
    ARBITRATOR = "Arbitrator"


# ─── Plan / controlled group / employer enums ─────────────────────────────────

class Industry(str, Enum):
    GENERAL = "GENERAL"
    CONSTRUCTION = "CONSTRUCTION"
    ENTERTAINMENT = "ENTERTAINMENT"
    TRUCKING = "TRUCKING"


class AllocationMethod(str, Enum):
    PRESUMPTIVE = "PRESUMPTIVE"
    MODIFIED_PRESUMPTIVE = "MODIFIED_PRESUMPTIVE"
    ROLLING_5 = "ROLLING_5"
    DIRECT_ATTRIBUTION = "DIRECT_ATTRIBUTION"


class DeMinimisVariant(str, Enum):
    STATUTORY = "STATUTORY"
    PLAN_ELECTED_HIGH = "PLAN_ELECTED_HIGH"


class CommonControlBasis(str, Enum):
    PARENT_SUBSIDIARY = "PARENT_SUBSIDIARY"
    BROTHER_SISTER = "BROTHER_SISTER"
    COMBINED = "COMBINED"


class BondPosture(str, Enum):
    UNBONDED = "UNBONDED"
    BONDED = "BONDED"


class CoveredWorkStatus(str, Enum):
    PERFORMING = "PERFORMING"
    CEASED = "CEASED"


class EmployerStatus(str, Enum):
    CONTRIBUTING = "CONTRIBUTING"
    PARTIAL_WITHDRAWN = "PARTIAL_WITHDRAWN"
    COMPLETE_WITHDRAWN = "COMPLETE_WITHDRAWN"
    DEFAULTED = "DEFAULTED"
    LIABILITY_SATISFIED = "LIABILITY_SATISFIED"


# ─── Certified-data enums ─────────────────────────────────────────────────────

class ValuationStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"


class ContributionRecordStatus(str, Enum):
    CERTIFIED = "CERTIFIED"
    AMENDED = "AMENDED"
    VOID = "VOID"


# ─── Withdrawal enums ─────────────────────────────────────────────────────────

class WithdrawalEventStatus(str, Enum):
    REPORTED = "REPORTED"
    COMPLETE_DETERMINED = "COMPLETE_DETERMINED"
    PARTIAL_DETERMINED = "PARTIAL_DETERMINED"
    NO_WITHDRAWAL = "NO_WITHDRAWAL"
    ASSESSED = "ASSESSED"


class WithdrawalType(str, Enum):
    NONE = "NONE"
    COMPLETE = "COMPLETE"
    PARTIAL_70_DECLINE = "PARTIAL_70_DECLINE"
    PARTIAL_CBA_CESSATION = "PARTIAL_CBA_CESSATION"
    PARTIAL_FACILITY_CESSATION = "PARTIAL_FACILITY_CESSATION"


class RulesVariant(str, Enum):
    GENERAL_RULES = "GENERAL_RULES"
    CONSTRUCTION_RULES = "CONSTRUCTION_RULES"
    ENTERTAINMENT_RULES = "ENTERTAINMENT_RULES"


class ReportedCause(str, Enum):
    CONTRIBUTION_OBLIGATION_CEASED = "CONTRIBUTION_OBLIGATION_CEASED"
    COVERED_WORK_CEASED = "COVERED_WORK_CEASED"
    CBA_PARTIAL_CESSATION = "CBA_PARTIAL_CESSATION"
    FACILITY_CESSATION = "FACILITY_CESSATION"
    CBU_DECLINE = "CBU_DECLINE"


# ─── Assessment enums (three independent dimensions) ──────────────────────────

class AssessmentLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    RESCINDED = "RESCINDED"
    FINAL = "FINAL"


class AssessmentReviewStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    DECIDED = "DECIDED"
    ARBITRATED = "ARBITRATED"


class AssessmentCollectionStatus(str, Enum):
    NOT_YET_DUE = "NOT_YET_DUE"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    ACCELERATED = "ACCELERATED"
    SATISFIED = "SATISFIED"


# ─── Schedule / instalment enums ──────────────────────────────────────────────

class PaymentScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEFAULT_ELIGIBLE = "DEFAULT_ELIGIBLE"
    NOTICED = "NOTICED"
    ACCELERATED = "ACCELERATED"
    SATISFIED = "SATISFIED"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class PaymentScheduleSource(str, Enum):
    ISSUANCE = "ISSUANCE"
    REVIEW_DECISION = "REVIEW_DECISION"
    ARBITRATION_AWARD = "ARBITRATION_AWARD"
    ACTUARIAL_CORRECTION = "ACTUARIAL_CORRECTION"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DUE = "DUE"
    DELINQUENT = "DELINQUENT"
    PAID = "PAID"
    VOID = "VOID"
    ACCELERATED = "ACCELERATED"


# ─── Review / arbitration enums ───────────────────────────────────────────────

class ReviewRequestStatus(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"
    DEEMED_DENIED = "DEEMED_DENIED"
    WITHDRAWN = "WITHDRAWN"


class ChallengedAssumption(str, Enum):
    NONE = "NONE"
    INTEREST_RATE = "INTEREST_RATE"
    MORTALITY = "MORTALITY"
    UVB_POOL_ALLOCATION = "UVB_POOL_ALLOCATION"


class ReviewDecision(str, Enum):
    NONE = "NONE"
    AFFIRMED = "AFFIRMED"
    REDUCED = "REDUCED"
    REVERSED = "REVERSED"


class AssumptionRuling(str, Enum):
    PENDING = "PENDING"
    SUSTAINED = "SUSTAINED"
    REJECTED = "REJECTED"
    NOT_RAISED = "NOT_RAISED"


class ArbitrationStatus(str, Enum):
    BRIEFING = "BRIEFING"
    HEARING = "HEARING"
    AWARD_ISSUED = "AWARD_ISSUED"
    REMANDED = "REMANDED"
    CLOSED = "CLOSED"


class AwardOutcome(str, Enum):
    NONE = "NONE"
    AFFIRM = "AFFIRM"
    REDUCE = "REDUCE"
    VACATE = "VACATE"
    REMAND = "REMAND"


# ─── Asset-sale enums ─────────────────────────────────────────────────────────

class AssetSaleTransactionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    EXEMPTION_CERTIFIED = "EXEMPTION_CERTIFIED"
    SUCCESSOR_DETERMINED = "SUCCESSOR_DETERMINED"
    REJECTED = "REJECTED"


class ExemptionStatus(str, Enum):
    PENDING = "PENDING"
    EXEMPT_4204 = "EXEMPT_4204"
    NOT_EXEMPT = "NOT_EXEMPT"


class SuccessorDetermination(str, Enum):
    PENDING = "PENDING"
    SUCCESSOR_LIABLE = "SUCCESSOR_LIABLE"
    NO_SUCCESSOR_LIABILITY = "NO_SUCCESSOR_LIABILITY"


class AdjudicationDisposition(str, Enum):
    CERTIFY_4204_EXEMPTION = "CERTIFY_4204_EXEMPTION"
    DETERMINE_SUCCESSOR = "DETERMINE_SUCCESSOR"
    REJECT = "REJECT"


# ─── Entity shapes ────────────────────────────────────────────────────────────

class Plan(TypedDict):
    id: str
    name: str
    industry: str
    allocation_method: str
    de_minimis_variant: str
    interest_rate_bps: int
    unattributable_uvb_cents: int
    mass_withdrawal_declared: bool
    employer_count: int
    issued_assessment_count: int
    created_at: str
    updated_at: str
    version: int


class ControlledGroup(TypedDict):
    id: str
    name: str
    common_control_basis: str
    bond_posture: str
    joint_exposure_cents: int
    contingent_exposure_cents: int
    exposure_score: float
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict):
    id: str
    plan_id: str
    controlled_group_id: str
    legal_name: str
    ein: str
    obligation_start_year: int
    covered_work_status: str
    cba_count: int
    directly_attributed_vested_benefits_cents: int
    directly_attributed_assets_cents: int
    status: str
    outstanding_liability_cents: int
    obligation_end_year: Optional[int]
    ceased_cba_count: int
    credit_watch: bool
    delinquency_strikes: int
    created_at: str
    updated_at: str
    version: int


class PlanYearValuation(TypedDict):
    id: str
    plan_id: str
    plan_year: int
    measurement_window_start: str
    measurement_window_end: str
    uvb_total_cents: int
    uvb_pool_cents: int
    all_employer_contributions_cents: int
    all_employer_cbu: int
    interest_rate_bps: int
    status: str
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    certify_on_create_used: bool
    allocated_uvb_cents: int
    unallocated_uvb_cents: int
    created_at: str
    updated_at: str
    version: int


class ContributionRecord(TypedDict):
    id: str
    employer_id: str
    plan_year_start: int
    plan_year_end: int
    contribution_base_units: int
    contribution_amount_cents: int
    contribution_rate_cents_per_cbu: int
    supersedes_record_id: Optional[str]
    status: str
    employer_version_at_apply: int
    created_at: str
    updated_at: str
    version: int


class WithdrawalEvent(TypedDict):
    id: str
    employer_id: str
    cessation_date: str
    withdrawal_plan_year: int
    reported_cause: str
    ceased_cba_count: int
    status: str
    determined_type: str
    rules_variant: str
    determined_at: Optional[str]
    partial_withdrawal_fraction: float
    decline_ratio: float
    high_base_year_average_cbu: float
    testing_period_average_cbu: float
    base_year_one: Optional[int]
    base_year_two: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PoolTermElement(TypedDict):
    plan_year: int
    decay_factor: float
    ratio: float
    term_cents: int


class LiabilityAssessment(TypedDict):
    id: str
    withdrawal_event_id: str
    valuation_id: str
    allocation_method_applied: str
    de_minimis_variant_applied: str
    interest_rate_bps_applied: int
    gross_allocated_cents: int
    de_minimis_reduction_cents: int
    award_adjustment_cents: int
    net_assessed_cents: int
    annual_payment_cents: int
    high_3yr_average_cbu: float
    high_3yr_window_start_year: int
    peak_contribution_rate_cents_per_cbu: int
    peak_rate_plan_year: int
    pool_term_breakdown: List[PoolTermElement]
    lifecycle_status: str
    review_status: str
    collection_status: str
    active_schedule_generation: int
    issued_at: Optional[str]
    issued_by_user_id: Optional[str]
    review_deadline_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PaymentSchedule(TypedDict):
    id: str
    liability_assessment_id: str
    generation_seq: int
    source: str
    annual_payment_cents: int
    applied_credit_cents: int
    amortization_basis_cents: int
    amortization_years: int
    forgiven_by_cap_cents: int
    capped_basis_cents: int
    installment_count: int
    quarterly_installment_cents: int
    final_installment_cents: int
    first_due_date: str
    status: str
    consecutive_delinquent_count: int
    default_notice_issued_at: Optional[str]
    cure_deadline_at: Optional[str]
    accelerated_balance_cents: int
    refund_due_cents: int
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    payment_schedule_id: str
    sequence_number: int
    principal_cents: int
    amount_due_cents: int
    amount_paid_cents: int
    due_date: str
    delinquent_on: str
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewRequest(TypedDict):
    id: str
    liability_assessment_id: str
    grounds_summary: str
    challenged_assumption: str
    proposed_interest_rate_bps: Optional[int]
    status: str
    filed_at: str
    filed_by_user_id: str
    plan_response_deadline_at: str
    arbitration_deadline_at: Optional[str]
    decision: str
    assumption_ruling: str
    recomputed_net_assessed_cents: Optional[int]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Arbitration(TypedDict):
    id: str
    liability_assessment_id: str
    review_request_id: str
    initiated_at: str
    round_number: int
    status: str
    award_outcome: str
    assumption_ruling: str
    awarded_net_assessed_cents: Optional[int]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetSaleTransaction(TypedDict):
    id: str
    seller_employer_id: str
    buyer_controlled_group_id: str
    closing_date: str
    closing_plan_year: int
    purchase_price_cents: int
    bond_amount_cents: int
    buyer_assumes_contribution_obligation: bool
    workforce_continuity_pct: float
    asset_continuity_pct: float
    customer_continuity_pct: float
    required_bond_cents: int
    status: str
    exemption_status: str
    successor_determination: str
    substantial_continuity_score: float
    bond_period_end_plan_year: Optional[int]
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
