"""Domain types for the CDFI certification and lending API.

State enums, role enum and one TypedDict per entity described by the PRD.
Every entity in this domain carries the four common fields (``id``,
``created_at``, ``updated_at``, ``version``).
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    INSTITUTION_OFFICER = "InstitutionOfficer"
    CERTIFICATION_REVIEWER = "CertificationReviewer"
    CREDIT_UNDERWRITER = "CreditUnderwriter"
    CREDIT_COMMITTEE = "CreditCommittee"
    COMPLIANCE_ANALYST = "ComplianceAnalyst"
    AWARD_ADMINISTRATOR = "AwardAdministrator"
    BORROWER = "Borrower"


ALL_ROLES = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# Enumerated values
# --------------------------------------------------------------------------
class InstitutionEntityType(str, Enum):
    LOAN_FUND = "LOAN_FUND"
    CREDIT_UNION = "CREDIT_UNION"
    BANK_HOLDING = "BANK_HOLDING"
    VENTURE_FUND = "VENTURE_FUND"


class ReserveMethod(str, Enum):
    MIGRATION_ANALYSIS = "MIGRATION_ANALYSIS"
    STATIC_POOL = "STATIC_POOL"


class CertificationState(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    RECERT_DUE = "RECERT_DUE"
    DECERTIFIED = "DECERTIFIED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class MarketType(str, Enum):
    INVESTMENT_AREA = "INVESTMENT_AREA"
    LOW_INCOME_TARGETED_POPULATION = "LOW_INCOME_TARGETED_POPULATION"
    OTHER_TARGETED_POPULATION = "OTHER_TARGETED_POPULATION"


class TargetMarketState(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


class ApplicationState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"


class TestVerdictState(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class CertificationTestCode(str, Enum):
    PRIMARY_MISSION = "PRIMARY_MISSION"
    FINANCING_ENTITY = "FINANCING_ENTITY"
    TARGET_MARKET = "TARGET_MARKET"
    DEVELOPMENT_SERVICES = "DEVELOPMENT_SERVICES"
    ACCOUNTABILITY = "ACCOUNTABILITY"
    NON_GOVERNMENT = "NON_GOVERNMENT"


class BoardStructure(str, Enum):
    GOVERNING_BOARD = "GOVERNING_BOARD"
    ADVISORY_BOARD = "ADVISORY_BOARD"


class BoardSeatStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"


class GeocodeState(str, Enum):
    UNGEOCODED = "UNGEOCODED"
    GEOCODED = "GEOCODED"
    GEOCODE_FAILED = "GEOCODE_FAILED"


class GeocodeOutcome(str, Enum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"


class CreditBuildingFeature(str, Enum):
    REPORTS_TO_BUREAUS = "REPORTS_TO_BUREAUS"
    SAVINGS_MATCH = "SAVINGS_MATCH"
    RATE_STEP_DOWN = "RATE_STEP_DOWN"
    DEFERRED_FIRST_PAYMENT = "DEFERRED_FIRST_PAYMENT"


class UnderwritingState(str, Enum):
    SCREENING = "SCREENING"
    UNDERWRITING = "UNDERWRITING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CLOSED = "CLOSED"


class ServicingState(str, Enum):
    NOT_DISBURSED = "NOT_DISBURSED"
    CURRENT = "CURRENT"
    DELINQUENT_30 = "DELINQUENT_30"
    DELINQUENT_60 = "DELINQUENT_60"
    DELINQUENT_90 = "DELINQUENT_90"
    CHARGED_OFF = "CHARGED_OFF"
    PAID_OFF = "PAID_OFF"


class RiskGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


class LoanDecision(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


class TATopic(str, Enum):
    CREDIT_BUILDING = "CREDIT_BUILDING"
    BUSINESS_PLANNING = "BUSINESS_PLANNING"
    HOMEBUYER_EDUCATION = "HOMEBUYER_EDUCATION"
    FINANCIAL_COACHING = "FINANCIAL_COACHING"


class TAEngagementState(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class TACloseOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class ImpactReportState(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"


class WeightingBasis(str, Enum):
    DOLLAR_WEIGHTED = "DOLLAR_WEIGHTED"
    COUNT_WEIGHTED = "COUNT_WEIGHTED"


class MeasurementState(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class MeasurementVerdict(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class AwardProgram(str, Enum):
    CDFI_PROGRAM_FA = "CDFI_PROGRAM_FA"
    CDFI_PROGRAM_TA = "CDFI_PROGRAM_TA"
    NEW_MARKETS = "NEW_MARKETS"
    CMF = "CMF"


class AwardState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    DISBURSING = "DISBURSING"
    DRAW_SUSPENDED = "DRAW_SUSPENDED"


class AwardDecision(str, Enum):
    AWARD = "AWARD"
    REJECT = "REJECT"


class MatchSourceType(str, Enum):
    CASH_PRIVATE = "CASH_PRIVATE"
    CASH_PUBLIC_NON_FEDERAL = "CASH_PUBLIC_NON_FEDERAL"
    IN_KIND = "IN_KIND"
    DEFERRED_PLEDGE = "DEFERRED_PLEDGE"
    FEDERAL = "FEDERAL"


class CommitmentStatus(str, Enum):
    PLEDGED = "PLEDGED"
    VERIFIED = "VERIFIED"
    WITHDRAWN = "WITHDRAWN"
    HELD = "HELD"


# --------------------------------------------------------------------------
# Entity shapes — every entity carries id / created_at / updated_at / version
# --------------------------------------------------------------------------
class Institution(TypedDict):
    id: str
    legal_name: str
    ein: str
    entity_type: str
    primary_mission_statement: str
    asset_size_cents: int
    loss_reserve_balance_cents: int
    reserve_method: str
    certification_state: str
    compliance_posture: str
    accountability_score: float
    accountability_satisfied: bool
    governing_seats_active: int
    advisory_seats_active: int
    portfolio_principal_outstanding_cents: int
    portfolio_principal_disbursed_cents: int
    loss_reserve_required_migration_cents: int
    loss_reserve_required_static_cents: int
    loss_reserve_required_cents: int
    reserve_coverage_ratio: float
    reserve_deficit_cents: int
    target_market_lending_pct: float
    jobs_created_total: int
    jobs_retained_total: int
    housing_units_total: int
    businesses_financed_total: int
    certified_at: Optional[str]
    recertification_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TargetMarket(TypedDict):
    id: str
    institution_id: str
    market_type: str
    name: str
    census_tract_codes: List[str]
    ami_threshold_pct: Optional[float]
    state: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificationApplication(TypedDict):
    id: str
    institution_id: str
    primary_mission_statement: str
    financing_activity_pct_claimed: float
    development_services_description: str
    state: str
    revision_round: int
    accountability_score_snapshot: float
    test_primary_mission_state: str
    test_financing_entity_state: str
    test_target_market_state: str
    test_development_services_state: str
    test_accountability_state: str
    test_non_government_state: str
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    info_requested_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoardSeat(TypedDict):
    id: str
    institution_id: str
    target_market_id: Optional[str]
    structure: str
    holder_name: str
    represents_target_market: bool
    status: str
    resigned_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Borrower(TypedDict):
    id: str
    institution_id: str
    full_name: str
    street_address: str
    postal_code: str
    household_income_cents: int
    area_median_income_cents: int
    credit_score: Optional[int]
    income_pct_ami: float
    census_tract_code: Optional[str]
    geocode_state: str
    geocode_attempts: int
    in_target_market: bool
    matched_target_market_type: Optional[str]
    ta_hours_total: float
    created_at: str
    updated_at: str
    version: int


class LoanProduct(TypedDict):
    id: str
    institution_id: str
    name: str
    base_rate_bps: int
    term_months: int
    max_dti_pct: float
    min_credit_score: int
    allow_no_credit_score: bool
    credit_building_features: List[str]
    requires_ta_completion: bool
    product_cap_cents: int
    committed_principal_cents: int
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict):
    id: str
    institution_id: str
    borrower_id: str
    product_id: str
    refinance_of_loan_id: Optional[str]
    requested_principal_cents: int
    approved_principal_cents: Optional[int]
    underwriting_state: str
    servicing_state: str
    verified_monthly_income_cents: Optional[int]
    existing_monthly_debt_cents: Optional[int]
    credit_score_at_underwriting: Optional[int]
    provisional_monthly_payment_cents: Optional[int]
    dti_pct: Optional[float]
    risk_grade: Optional[str]
    risk_spread_bps: Optional[int]
    ta_discount_bps: Optional[int]
    final_rate_bps: Optional[int]
    monthly_payment_cents: Optional[int]
    principal_disbursed_cents: int
    principal_repaid_cents: int
    principal_outstanding_cents: int
    charged_off_principal_cents: int
    first_disbursed_on: Optional[str]
    next_payment_due_on: Optional[str]
    days_past_due: int
    borrower_in_target_market_at_origination: bool
    vintage_year: Optional[int]
    underwritten_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TAEngagement(TypedDict):
    id: str
    institution_id: str
    borrower_id: str
    loan_id: Optional[str]
    topic: str
    scheduled_start_at: str
    scheduled_end_at: str
    planned_hours: float
    actual_hours: Optional[float]
    competency_verified: bool
    state: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImpactReport(TypedDict):
    id: str
    loan_id: str
    borrower_id: str
    reporting_period_end: str
    jobs_created: int
    jobs_retained: int
    housing_units: int
    businesses_financed: int
    state: str
    dispute_reason: Optional[str]
    verified_at: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class ComplianceMeasurement(TypedDict):
    id: str
    institution_id: str
    period_start: str
    period_end: str
    weighting_basis: str
    state: str
    measured_loan_count: int
    target_market_loan_count: int
    measured_principal_cents: int
    target_market_principal_cents: int
    dollar_weighted_pct: Optional[float]
    count_weighted_pct: Optional[float]
    selected_pct: Optional[float]
    verdict: str
    void_reason: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AwardApplication(TypedDict):
    id: str
    institution_id: str
    program: str
    requested_amount_cents: int
    match_ratio_pct: float
    required_match_cents: int
    match_eligible_cents: int
    match_shortfall_cents: int
    performance_goal_jobs: int
    performance_goal_housing_units: int
    period_start: str
    period_end: str
    awarded_amount_cents: Optional[int]
    goal_attainment_pct: float
    state: str
    suspension_reason: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MatchingFundCommitment(TypedDict):
    id: str
    award_application_id: str
    source_name: str
    source_type: str
    amount_cents: int
    committed_on: str
    eligible_cents: int
    status: str
    verified_by_user_id: Optional[str]
    withdraw_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
