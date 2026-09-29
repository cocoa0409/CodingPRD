"""Domain types for the bank-owned life insurance funding platform.

Entity shapes, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD section 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BENEFITS_ANALYST = "BenefitsAnalyst"
    RISK_OFFICER = "RiskOfficer"
    TREASURY_CONTROLLER = "TreasuryController"
    CLAIMS_ADMINISTRATOR = "ClaimsAdministrator"
    BOARD_SECRETARY = "BoardSecretary"
    CARRIER_LIAISON = "CarrierLiaison"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class CarrierStatus(str, Enum):
    PENDING_DILIGENCE = "PENDING_DILIGENCE"
    AUTHORIZED = "AUTHORIZED"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AmBestRating(str, Enum):
    A_PLUS_PLUS = "A_PLUS_PLUS"
    A_PLUS = "A_PLUS"
    A = "A"
    A_MINUS = "A_MINUS"
    B_PLUS_PLUS = "B_PLUS_PLUS"
    B_PLUS = "B_PLUS"
    B = "B"


class ProductTypeStatus(str, Enum):
    OPEN = "OPEN"
    ON_WATCH = "ON_WATCH"
    CLOSED_TO_NEW = "CLOSED_TO_NEW"


class AccountType(str, Enum):
    GENERAL = "GENERAL"
    SEPARATE = "SEPARATE"
    HYBRID = "HYBRID"


class MecStatus(str, Enum):
    MEC = "MEC"
    NON_MEC = "NON_MEC"


class DiligenceReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class InsurableInterestStatus(str, Enum):
    NOT_ESTABLISHED = "NOT_ESTABLISHED"
    ESTABLISHED = "ESTABLISHED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    DECEASED = "DECEASED"


class ConsentRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PurchaseRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DILIGENCE_CLEARED = "DILIGENCE_CLEARED"
    CAPACITY_RESERVED = "CAPACITY_RESERVED"
    NOTICE_FILED = "NOTICE_FILED"
    CONCURRENCE_PENDING = "CONCURRENCE_PENDING"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PolicyStatus(str, Enum):
    IN_FORCE = "IN_FORCE"
    PENDING_EXCHANGE = "PENDING_EXCHANGE"
    CLAIM_PENDING = "CLAIM_PENDING"
    EXCHANGED = "EXCHANGED"
    SURRENDERED = "SURRENDERED"
    PAID_OUT = "PAID_OUT"


class NqdcPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    TERMINATED = "TERMINATED"


class NqdcPlanType(str, Enum):
    SERP = "SERP"
    DEFERRED_BONUS = "DEFERRED_BONUS"
    DIRECTOR_FEE = "DIRECTOR_FEE"


class FundingPosture(str, Enum):
    FUNDED = "FUNDED"
    UNDERFUNDED = "UNDERFUNDED"
    CRITICAL = "CRITICAL"


class LiabilityBasis(str, Enum):
    ACCRUAL = "ACCRUAL"
    PBO = "PBO"


class NqdcLiabilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"


class ClaimAdjudicationStatus(str, Enum):
    FILED = "FILED"
    UNDER_ADJUDICATION = "UNDER_ADJUDICATION"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    VOIDED = "VOIDED"


class ClaimDistributionStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ALLOCATED = "ALLOCATED"
    DISTRIBUTED = "DISTRIBUTED"


class BeneficiaryRelationship(str, Enum):
    SPOUSE = "SPOUSE"
    CHILD = "CHILD"
    TRUST = "TRUST"
    ESTATE = "ESTATE"


class BeneficiaryAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class DispositionType(str, Enum):
    FULL_SURRENDER = "FULL_SURRENDER"
    PARTIAL_SURRENDER = "PARTIAL_SURRENDER"
    EXCHANGE_1035 = "EXCHANGE_1035"


class CostRecoveryMethod(str, Enum):
    FIFO_BASIS_FIRST = "FIFO_BASIS_FIRST"
    LIFO_INCOME_FIRST = "LIFO_INCOME_FIRST"


class AnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    REVIEWED = "REVIEWED"
    COMMITTED = "COMMITTED"
    EXECUTED = "EXECUTED"
    ABANDONED = "ABANDONED"
    REJECTED = "REJECTED"


class RiskAssessmentStatus(str, Enum):
    COMPILED = "COMPILED"
    BOARD_SUBMITTED = "BOARD_SUBMITTED"
    BOARD_ACCEPTED = "BOARD_ACCEPTED"
    RETURNED = "RETURNED"


class RiskRating(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


# --------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------
class Carrier(TypedDict):
    id: str
    legal_name: str
    naic_code: str
    am_best_rating: str
    statutory_surplus_usd: float
    domicile_state: str
    status: str
    watch_list_flag: bool
    reserved_premium_usd: float
    in_force_premium_usd: float
    in_force_cash_value_usd: float
    concentration_bps: int
    regulatory_notice_count: int
    last_approved_review_year: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ProductType(TypedDict):
    id: str
    carrier_id: str
    product_name: str
    account_type: str
    mec_status: str
    disclosed_me_charge_bps: int
    guaranteed_min_crediting_bps: int
    status: str
    consecutive_low_yield_count: int
    latest_me_charge_bps: int
    latest_me_drift_bps: int
    created_at: str
    updated_at: str
    version: int


class DiligenceReview(TypedDict):
    id: str
    carrier_id: str
    review_year: int
    rating_points: Optional[int]
    surplus_points: Optional[int]
    concentration_points: Optional[float]
    financial_strength_score: Optional[int]
    status: str
    info_request_count: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    full_name: str
    employee_number: str
    annual_salary_usd: float
    officer_flag: bool
    insurable_interest_status: str
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict):
    id: str
    employee_id: str
    coverage_start_date: str
    coverage_end_date: str
    consent_form_reference: str
    notice_and_consent_version: str
    status: str
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PolicyPurchaseRequest(TypedDict):
    id: str
    carrier_id: str
    product_type_id: str
    employee_id: str
    single_premium_usd: float
    face_amount_usd: float
    requested_effective_date: str
    status: str
    reserved_premium_usd: float
    base_ratio_bps: int
    effective_limit_pct: float
    aggregate_limit_usd: float
    headroom_usd: float
    carrier_concentration_bps: int
    notice_required: bool
    notice_filed_at: Optional[str]
    notice_waiting_ends_at: Optional[str]
    concurrence_requested_at: Optional[str]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    purchase_request_id: str
    carrier_id: str
    product_type_id: str
    employee_id: str
    exchanged_from_policy_id: Optional[str]
    policy_number: str
    issue_date: str
    single_premium_usd: float
    face_amount_usd: float
    cost_basis_usd: float
    cash_surrender_value_usd: float
    policy_year: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NqdcPlan(TypedDict):
    id: str
    plan_name: str
    plan_type: str
    discount_rate_bps: int
    status: str
    accrual_liability_usd: float
    pbo_liability_usd: float
    matched_cash_value_usd: float
    funding_posture: str
    funded_ratio_bps: int
    created_at: str
    updated_at: str
    version: int


class NqdcParticipantLiability(TypedDict):
    id: str
    nqdc_plan_id: str
    employee_id: str
    matched_policy_id: Optional[str]
    accrued_to_date_usd: float
    projected_benefit_usd: float
    years_to_payout: int
    discounted_benefit_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DeathBenefitClaim(TypedDict):
    id: str
    policy_id: str
    date_of_death: str
    terminal_dividend_usd: float
    proof_reference: str
    total_death_benefit_usd: Optional[float]
    survivor_entitlement_usd: Optional[float]
    bank_portion_usd: Optional[float]
    adjudication_status: str
    distribution_status: str
    allocated_bps_total: int
    filed_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BeneficiaryAllocation(TypedDict):
    id: str
    claim_id: str
    beneficiary_name: str
    relationship: str
    allocation_pct_bps: int
    gross_amount_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ExchangeSurrenderAnalysis(TypedDict):
    id: str
    policy_id: str
    replacement_carrier_id: Optional[str]
    disposition_type: str
    requested_withdrawal_usd: float
    cost_recovery_method: str
    taxable_gain_usd: float
    surrender_charge_usd: float
    tax_liability_usd: float
    net_proceeds_usd: float
    status: str
    resulting_policy_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict):
    id: str
    capital_position_id: str
    assessment_year: int
    restricted_carrier_count: int
    watch_list_carrier_count: int
    on_watch_product_count: int
    closed_product_count: int
    critical_plan_count: int
    underfunded_plan_count: int
    risk_points: int
    risk_rating: str
    status: str
    compiled_at: str
    board_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------
# Entities carrying ONLY id + created_at
#
# A filed capital snapshot and a posted carrier statement period are immutable
# facts: they have no updated_at field and no version field at all.
# --------------------------------------------------------------------------
class CapitalPosition(TypedDict):
    id: str
    as_of_date: str
    tier1_capital_usd: float
    total_assets_usd: float
    recorded_by_user_id: str
    created_at: str


class PolicyValuation(TypedDict):
    id: str
    policy_id: str
    period_start_date: str
    as_of_date: str
    prior_cash_value_usd: float
    credited_interest_usd: float
    mortality_expense_charge_usd: float
    market_value_adjustment_usd: float
    gross_crediting_rate_bps: int
    cash_value_usd: float
    net_yield_bps: int
    me_charge_bps: int
    me_drift_bps: int
    recorded_by_user_id: str
    created_at: str
