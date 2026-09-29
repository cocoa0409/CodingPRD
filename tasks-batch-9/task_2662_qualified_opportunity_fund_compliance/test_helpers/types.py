"""
Typed shapes for every entity the Qualified Opportunity Fund compliance API
returns, plus the string enums the PRD declares.

Common properties: every entity carries `id`, `created_at`, `updated_at` and
`version` — except CapitalExpenditure, which the PRD declares as an immutable
ledger row carrying only `id` and `created_at`.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# =========================================================================
# Enums
# =========================================================================


class Role(str, Enum):
    FUND_MANAGER = "FundManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    INVESTOR = "Investor"
    PLATFORM_ADMIN = "PlatformAdmin"


class TaxpayerType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    PARTNERSHIP = "PARTNERSHIP"
    C_CORPORATION = "C_CORPORATION"
    TRUST = "TRUST"


class AttestationStatus(str, Enum):
    PENDING = "PENDING"
    ATTESTED = "ATTESTED"
    BLOCKED = "BLOCKED"


class FundEntityType(str, Enum):
    CORPORATION = "CORPORATION"
    PARTNERSHIP = "PARTNERSHIP"


class ValuationMethod(str, Enum):
    APPLICABLE_FINANCIAL_STATEMENT = "APPLICABLE_FINANCIAL_STATEMENT"
    UNADJUSTED_COST_BASIS = "UNADJUSTED_COST_BASIS"


class CertificationStatus(str, Enum):
    DRAFT = "DRAFT"
    SELF_CERTIFIED = "SELF_CERTIFIED"
    DECERTIFIED = "DECERTIFIED"


class CompliancePosture(str, Enum):
    UNTESTED = "UNTESTED"
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"
    CURE_PENDING = "CURE_PENDING"
    FAILED_FINAL = "FAILED_FINAL"


class GainCharacter(str, Enum):
    SHORT_TERM_CAPITAL = "SHORT_TERM_CAPITAL"
    LONG_TERM_CAPITAL = "LONG_TERM_CAPITAL"
    SECTION_1231_NET = "SECTION_1231_NET"
    ORDINARY = "ORDINARY"


class DeadlineBasis(str, Enum):
    SALE_DATE = "SALE_DATE"
    PARTNERSHIP_YEAR_END = "PARTNERSHIP_YEAR_END"
    SECTION_1231_YEAR_END = "SECTION_1231_YEAR_END"


class GainStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    PARTIALLY_INVESTED = "PARTIALLY_INVESTED"
    FULLY_INVESTED = "FULLY_INVESTED"
    EXPIRED = "EXPIRED"


class HoldingTier(str, Enum):
    UNDER_FIVE = "UNDER_FIVE"
    FIVE_YEAR = "FIVE_YEAR"
    SEVEN_YEAR = "SEVEN_YEAR"
    TEN_YEAR = "TEN_YEAR"


class ElectionStatus(str, Enum):
    DEFERRED = "DEFERRED"
    STEPPED_UP = "STEPPED_UP"
    INCLUDED_PARTIAL = "INCLUDED_PARTIAL"
    INCLUDED_FULL = "INCLUDED_FULL"
    REVOKED = "REVOKED"


class RevokedReasonCode(str, Enum):
    NONE = "NONE"
    INVESTOR_WITHDRAWAL = "INVESTOR_WITHDRAWAL"
    FUND_REJECTED = "FUND_REJECTED"
    ADMIN_CORRECTION = "ADMIN_CORRECTION"


class AssetClass(str, Enum):
    QOZ_BUSINESS_PROPERTY = "QOZ_BUSINESS_PROPERTY"
    QOZB_EQUITY = "QOZB_EQUITY"
    NONQUALIFIED_FINANCIAL_PROPERTY = "NONQUALIFIED_FINANCIAL_PROPERTY"
    CASH = "CASH"


class Qualification(str, Enum):
    QUALIFIED = "QUALIFIED"
    NONQUALIFIED = "NONQUALIFIED"
    IMPROVEMENT_PENDING = "IMPROVEMENT_PENDING"


class AssetStatus(str, Enum):
    HELD = "HELD"
    IMPROVING = "IMPROVING"
    DISPOSED = "DISPOSED"


class BusinessQualificationStatus(str, Enum):
    UNTESTED = "UNTESTED"
    QUALIFIED = "QUALIFIED"
    AT_RISK = "AT_RISK"
    DISQUALIFIED = "DISQUALIFIED"


class SafeHarbor(str, Enum):
    FIFTY_PCT_HOURS = "FIFTY_PCT_HOURS"
    FIFTY_PCT_AMOUNTS_PAID = "FIFTY_PCT_AMOUNTS_PAID"
    MANAGEMENT_AND_TANGIBLE = "MANAGEMENT_AND_TANGIBLE"
    GROSS_INCOME_ACTUAL = "GROSS_INCOME_ACTUAL"


class ProngVerdict(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class BusinessTestStatus(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class AssetTestResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class AssetTestStatus(str, Enum):
    DRAFT = "DRAFT"
    MEASURED = "MEASURED"
    CERTIFIED_PASS = "CERTIFIED_PASS"
    CERTIFIED_FAIL = "CERTIFIED_FAIL"


class AggregationMethod(str, Enum):
    ASSET_BY_ASSET = "ASSET_BY_ASSET"
    AGGREGATED_GROUP = "AGGREGATED_GROUP"


class ProjectStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    LAPSED = "LAPSED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    BLOWN = "BLOWN"


class ExpenditureKind(str, Enum):
    CAPITALIZED_IMPROVEMENT = "CAPITALIZED_IMPROVEMENT"
    OPERATING_WORKING_CAPITAL = "OPERATING_WORKING_CAPITAL"
    LAND_ACQUISITION = "LAND_ACQUISITION"


class CureBasis(str, Enum):
    NONE = "NONE"
    REASONABLE_CAUSE = "REASONABLE_CAUSE"
    TREATED_AS_FAILURE = "TREATED_AS_FAILURE"


class AssessmentStatus(str, Enum):
    ASSESSED = "ASSESSED"
    CURE_REQUESTED = "CURE_REQUESTED"
    CURED = "CURED"
    UPHELD = "UPHELD"


class CureDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class InclusionEventType(str, Enum):
    SALE_OF_INTEREST = "SALE_OF_INTEREST"
    GIFT_TRANSFER = "GIFT_TRANSFER"
    FUND_DECERTIFICATION = "FUND_DECERTIFICATION"
    PARTIAL_REDEMPTION = "PARTIAL_REDEMPTION"
    DEC_31_2026_STATUTORY = "DEC_31_2026_STATUTORY"


class StepUpStatus(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class DenialReason(str, Enum):
    NONE = "NONE"
    HOLD_UNDER_TEN_YEARS = "HOLD_UNDER_TEN_YEARS"
    FUND_DECERTIFIED = "FUND_DECERTIFIED"
    PRIOR_FULL_INCLUSION = "PRIOR_FULL_INCLUSION"


# =========================================================================
# Common property mixins
# =========================================================================


class CommonFields(TypedDict):
    """Common properties every mutable entity carries."""

    id: str
    created_at: str
    updated_at: str
    version: int


class LedgerFields(TypedDict):
    """Common properties for the append-only CapitalExpenditure ledger row."""

    id: str
    created_at: str


# =========================================================================
# Entities
# =========================================================================


class Investor(CommonFields):
    legal_name: str
    taxpayer_type: str
    tax_year_end_month: int
    compliance_attestation_status: str
    eligible_gain_total: float
    deferred_gain_outstanding: float
    included_gain_total: float


class Fund(CommonFields):
    name: str
    entity_type: str
    manager_user_id: str
    asset_test_valuation_method: str
    certification_status: str
    compliance_posture: str
    first_taxable_month_iso8601: Optional[str]
    self_certification_date: Optional[str]
    aggregate_asset_basis: float
    aggregate_qualified_basis: float
    aggregate_afs_value: float
    aggregate_qualified_afs_value: float
    deferred_gain_committed: float
    cumulative_penalty_months: int
    consecutive_failed_tests: int
    last_test_measurement_date: Optional[str]


class EligibleGain(CommonFields):
    investor_id: str
    gain_character: str
    eligible_amount: float
    realization_date: str
    deadline_basis: str
    pass_through_year_end: Optional[str]
    window_basis_date: str
    investment_deadline: str
    elected_amount: float
    unelected_amount: float
    status: str
    expired_at: Optional[str]


class DeferralElection(CommonFields):
    eligible_gain_id: str
    fund_id: str
    investor_id: str
    elected_amount: float
    investment_date: str
    days_from_basis: int
    initial_basis: float
    current_basis: float
    step_up_applied_pct: float
    holding_tier: str
    included_amount: float
    included_fraction_total: float
    deferred_remaining: float
    status: str
    revoked_reason_code: str


class FundAsset(CommonFields):
    fund_id: str
    qoz_business_id: Optional[str]
    asset_class: str
    acquisition_date: str
    acquired_from_related_party: bool
    original_use_in_zone: bool
    unadjusted_cost_basis: float
    afs_fair_value: float
    adjusted_basis: float
    qualification: str
    status: str
    disposed_at: Optional[str]
    disposition_sequence_index: Optional[int]
    proceeds_amount: Optional[float]


class QOZBusiness(CommonFields):
    fund_id: str
    legal_name: str
    zone_tract_code: str
    declared_nqfp_amount: float
    total_asset_value: float
    total_tangible_property_basis: float
    wcsh_protected_amount: float
    blown_unspent_amount: float
    nqfp_amount: float
    qualification_status: str
    consecutive_failed_business_tests: int


class BusinessTest(CommonFields):
    qoz_business_id: str
    testing_date: str
    safe_harbor_used: Optional[str]
    hours_zone_pct: Optional[float]
    amounts_paid_zone_pct: Optional[float]
    gross_income_zone_amount: Optional[float]
    gross_income_total_amount: Optional[float]
    intangibles_zone_use_amount: Optional[float]
    intangibles_total_amount: Optional[float]
    total_asset_value_measured: Optional[float]
    nqfp_amount_measured: Optional[float]
    gross_income_pct: Optional[float]
    intangibles_pct: Optional[float]
    nqfp_pct: Optional[float]
    gross_income_prong: str
    intangibles_prong: str
    nqfp_prong: str
    status: str
    measured_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]


class AssetTest(CommonFields):
    fund_id: str
    measurement_date: str
    period_start: str
    period_end: str
    valuation_method: str
    qualified_numerator: float
    total_denominator: float
    ratio_pct: float
    included_asset_count: int
    result: str
    shortfall_amount: float
    failed_month_count: int
    status: str
    measured_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]


class ImprovementProject(CommonFields):
    fund_asset_id: str
    window_start: str
    window_end: str
    aggregation_method: str
    group_key: Optional[str]
    basis_at_acquisition: float
    qualified_additions_total: float
    improvement_ratio_pct: float
    status: str
    evaluated_at: Optional[str]


class SpendScheduleRow(TypedDict):
    month_index: int
    planned_amount: float


class WorkingCapitalPlan(CommonFields):
    qoz_business_id: str
    window_start: str
    window_end: str
    covered_amount: float
    written_plan_reference: str
    schedule_month_count: int
    spend_schedule: List[SpendScheduleRow]
    documentation_complete: bool
    spent_total: float
    unspent_amount: float
    last_checkpoint_month_index: int
    pacing_shortfall: float
    overspill_amount: float
    status: str


class CapitalExpenditure(LedgerFields):
    """Immutable ledger row: only `id` and `created_at` from the common set."""

    improvement_project_id: Optional[str]
    wcsh_plan_id: Optional[str]
    amount: float
    expenditure_kind: str
    spend_date: str
    counts_toward_basis: bool
    schedule_month_index: Optional[int]


class PenaltyAssessment(CommonFields):
    fund_id: str
    asset_test_id: str
    failed_month_count: int
    shortfall_amount: float
    monthly_penalty_amount: float
    gross_penalty_amount: float
    cure_credit_amount: float
    net_penalty_amount: float
    cure_attempt_count: int
    cure_basis: str
    narrative_reference: Optional[str]
    status: str
    requested_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]


class InclusionEvent(CommonFields):
    deferral_election_id: str
    event_type: str
    included_fraction: float
    event_date: str
    holding_days: int
    holding_tier_applied: str
    gross_inclusion_amount: float
    basis_offset_amount: float
    net_inclusion_amount: float
    is_full: bool


class StepUpElection(CommonFields):
    deferral_election_id: str
    claimed_fmv: float
    disposition_sequence: List[str]
    election_date: str
    holding_period_days: int
    stepped_up_basis: Optional[float]
    status: str
    denial_reason: str


# =========================================================================
# Computed read models
# =========================================================================


class InvestorStatement(TypedDict):
    investor_id: str
    eligible_gain_total: float
    deferred_gain_outstanding: float
    included_gain_total: float
    election_count: int
    inclusion_event_count: int


class ClockState(TypedDict):
    current_utc: str


class ClockSetResult(TypedDict):
    current_utc: str
    previous_utc: str


class DeadlineSweepResult(TypedDict):
    expired_gain_count: int
    lapsed_project_count: int
    blown_plan_count: int
    swept_at: str


# Loose alias for any entity payload read out of an envelope.
EntityPayload = Dict[str, Any]
