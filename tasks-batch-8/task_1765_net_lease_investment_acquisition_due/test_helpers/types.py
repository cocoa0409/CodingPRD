"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ACQUISITIONS_ANALYST = "AcquisitionsAnalyst"
    UNDERWRITING_COMMITTEE = "UnderwritingCommittee"
    DUE_DILIGENCE_OFFICER = "DueDiligenceOfficer"
    CAPITAL_MARKETS_OFFICER = "CapitalMarketsOfficer"
    ESCROW_OFFICER = "EscrowOfficer"
    ASSET_MANAGER = "AssetManager"
    PLATFORM_ADMIN = "PlatformAdmin"


class DealStatus(str, Enum):
    SOURCING = "SOURCING"
    PSA_PENDING = "PSA_PENDING"
    PSA_EXECUTED = "PSA_EXECUTED"
    DUE_DILIGENCE = "DUE_DILIGENCE"
    CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class DealPosture(str, Enum):
    SOURCING = "SOURCING"
    UNDER_REVIEW = "UNDER_REVIEW"
    DD_OPEN = "DD_OPEN"
    DD_BLOCKED = "DD_BLOCKED"
    CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class TenantCreditStatus(str, Enum):
    PENDING = "PENDING"
    ANALYZED = "ANALYZED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PropertyStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    SURVEYED = "SURVEYED"
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    VERIFIED = "VERIFIED"
    ESTOPPEL_PENDING = "ESTOPPEL_PENDING"
    ESTOPPELED = "ESTOPPELED"
    EXPIRED = "EXPIRED"


class RolloverRiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ModelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PsaStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    AMENDED = "AMENDED"
    TERMINATED = "TERMINATED"
    CLOSED = "CLOSED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    SATISFIED = "SATISFIED"
    WAIVED = "WAIVED"
    OVERDUE = "OVERDUE"


class MilestoneType(str, Enum):
    TITLE_REVIEW = "TITLE_REVIEW"
    SURVEY_REVIEW = "SURVEY_REVIEW"
    ENVIRONMENTAL = "ENVIRONMENTAL"
    PCA = "PCA"
    ESTOPPEL_COLLECTION = "ESTOPPEL_COLLECTION"
    SNDA_COLLECTION = "SNDA_COLLECTION"
    FINANCING_COMMITMENT = "FINANCING_COMMITMENT"
    FINAL_WALKTHROUGH = "FINAL_WALKTHROUGH"


class TitleReviewStatus(str, Enum):
    RECEIVED = "RECEIVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    EXCEPTIONS_RAISED = "EXCEPTIONS_RAISED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class ExceptionSeverity(str, Enum):
    STANDARD = "STANDARD"
    MATERIAL = "MATERIAL"
    FATAL = "FATAL"


class TitleExceptionStatus(str, Enum):
    OPEN = "OPEN"
    CURE_PROPOSED = "CURE_PROPOSED"
    CURED = "CURED"
    WAIVED = "WAIVED"
    SUPERSEDED = "SUPERSEDED"


class EaStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    CLEARED = "CLEARED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"


class PcaStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class EstoppelStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    CERTIFIED = "CERTIFIED"
    DEFICIENT = "DEFICIENT"
    EXPIRED = "EXPIRED"


class SndaStatus(str, Enum):
    REQUESTED = "REQUESTED"
    RECEIVED = "RECEIVED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class FinancingStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COMMITTED = "COMMITTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    LAPSED = "LAPSED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    TRUED_UP = "TRUED_UP"
    SUPERSEDED = "SUPERSEDED"


class ProrationLineType(str, Enum):
    BASE_RENT = "BASE_RENT"
    CAM = "CAM"
    TAX = "TAX"
    INSURANCE = "INSURANCE"
    UTILITY = "UTILITY"


class ProrationDirection(str, Enum):
    BUYER_CREDIT = "BUYER_CREDIT"
    SELLER_CREDIT = "SELLER_CREDIT"


class TrueUpStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ESCROW_APPROVED = "ESCROW_APPROVED"
    FULLY_APPROVED = "FULLY_APPROVED"
    REJECTED = "REJECTED"
    APPLIED = "APPLIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities with versioned resources carry id + created_at + updated_at +
# version. Proration lines are immutable once created, so the Proration
# TypedDict carries only id + created_at (no updated_at, no version).
# ---------------------------------------------------------------------------


class Deal(TypedDict, total=False):
    id: str
    deal_name: str
    deal_type: str
    sourcing_channel: str
    target_close_date: str
    earnest_money_cents: int
    purchase_price_cents: int
    posture: str
    dd_period_end: Optional[str]
    financing_contingency_end: Optional[str]
    earnest_money_released: bool
    pinned_underwriting_model_id: Optional[str]
    closing_statement_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict, total=False):
    id: str
    legal_name: str
    credit_rating: str
    credit_score: int
    annual_revenue_cents: int
    is_guaranteed: bool
    credit_assessment_status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    deal_id: str
    address: str
    property_type: str
    rentable_sqft: int
    year_built: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    property_id: str
    tenant_id: str
    lease_type: str
    annual_base_rent_cents: int
    lease_commencement_date: str
    lease_expiration_date: str
    remaining_term_months: int
    renewal_options_count: int
    rollover_risk_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class UnderwritingModel(TypedDict, total=False):
    id: str
    deal_id: str
    model_version: int
    noi_cents: int
    cap_rate_bps: int
    cash_on_cash_bps: int
    opex_allowance_variant: str
    walt_months: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseAgreement(TypedDict, total=False):
    id: str
    deal_id: str
    psa_price_cents: int
    earnest_money_cents: int
    dd_period_days: int
    financing_contingency_days: int
    executed_at: Optional[str]
    amendment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DueDiligenceMilestone(TypedDict, total=False):
    id: str
    deal_id: str
    milestone_type: str
    due_date: str
    completed_at: Optional[str]
    waived: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleReview(TypedDict, total=False):
    id: str
    deal_id: str
    title_company: str
    survey_type: str
    received_at: str
    exception_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TitleException(TypedDict, total=False):
    id: str
    title_review_id: str
    exception_code: str
    severity: str
    description: str
    cured_by_exception_id: Optional[str]
    cure_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EnvironmentalAssessment(TypedDict, total=False):
    id: str
    deal_id: str
    phase: str
    recognized_environmental_condition: bool
    remediation_cost_cents: int
    reliance_letter_received: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PropertyConditionAssessment(TypedDict, total=False):
    id: str
    deal_id: str
    immediate_repair_cost_cents: int
    capital_reserve_cents_per_sqft: int
    total_reserve_cents: int
    condition_rating: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EstoppelCertificate(TypedDict, total=False):
    id: str
    deal_id: str
    lease_id: str
    tenant_id: str
    rent_confirmed_cents: int
    default_confirmed: bool
    deficiency_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Snda(TypedDict, total=False):
    id: str
    deal_id: str
    lease_id: str
    lender_name: str
    non_disturbance_confirmed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancingApplication(TypedDict, total=False):
    id: str
    deal_id: str
    loan_type: str
    loan_amount_cents: int
    interest_rate_bps: int
    amortization_months: int
    annual_debt_service_cents: int
    dscr: float
    assumption_fee_cents: int
    committed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosingStatement(TypedDict, total=False):
    id: str
    deal_id: str
    statement_version: int
    closing_date: str
    total_prorations_cents: int
    cash_to_close_cents: int
    provisional: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Proration(TypedDict, total=False):
    # Immutable line item: id + created_at only — no updated_at, no version.
    id: str
    closing_statement_id: str
    line_type: str
    lease_id: str
    annual_amount_cents: int
    period_start: str
    period_end: str
    prorated_cents: int
    direction: str
    created_at: str


class TrueUpAdjustment(TypedDict, total=False):
    id: str
    closing_statement_id: str
    line_type: str
    amount_cents: int
    reason: str
    approved: bool
    status: str
    created_at: str
    updated_at: str
    version: int
