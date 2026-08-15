"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FOUNDATION_ADMIN = "FoundationAdmin"
    GIFT_OFFICER = "GiftOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FINANCE_OFFICER = "FinanceOfficer"
    PROGRAM_OFFICER = "ProgramOfficer"
    INVESTMENT_MANAGER = "InvestmentManager"
    ADVISOR = "Advisor"
    APPLICANT = "Applicant"
    COMMITTEE_MEMBER = "CommitteeMember"


class FundType(str, Enum):
    DONOR_ADVISED = "DONOR_ADVISED"
    DESIGNATED = "DESIGNATED"
    SCHOLARSHIP = "SCHOLARSHIP"


class FundStatus(str, Enum):
    PENDING_AGREEMENT = "PENDING_AGREEMENT"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DORMANT = "DORMANT"
    CLOSED = "CLOSED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class SpendingFormula(str, Enum):
    AVERAGE_12Q = "AVERAGE_12Q"
    FIXED_3YR = "FIXED_3YR"


class FeeTierSchedule(str, Enum):
    STANDARD = "STANDARD"
    FLAT = "FLAT"


class AdvisorKind(str, Enum):
    PRIMARY = "PRIMARY"
    SUCCESSOR = "SUCCESSOR"


class AdvisorStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    RESIGNED = "RESIGNED"
    DECEASED = "DECEASED"
    REVOKED = "REVOKED"


class AssetKind(str, Enum):
    CASH = "CASH"
    PUBLICLY_TRADED = "PUBLICLY_TRADED"
    RESTRICTED_STOCK = "RESTRICTED_STOCK"
    REAL_PROPERTY = "REAL_PROPERTY"


class AcceptanceStatus(str, Enum):
    PLEDGED = "PLEDGED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class LiquidationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING_LIQUIDATION = "PENDING_LIQUIDATION"
    LIQUIDATED = "LIQUIDATED"


class PoolKind(str, Enum):
    CONSERVATIVE = "CONSERVATIVE"
    BALANCED = "BALANCED"
    GROWTH = "GROWTH"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class UnitizationEventKind(str, Enum):
    BUY_IN = "BUY_IN"
    REDEMPTION = "REDEMPTION"
    MARK_TO_MARKET = "MARK_TO_MARKET"


class IrsSubsection(str, Enum):
    C3_501 = "C3_501"
    C3_PRIVATE_FOUNDATION = "C3_PRIVATE_FOUNDATION"
    GOVERNMENT = "GOVERNMENT"
    OTHER = "OTHER"


class DueDiligenceStatus(str, Enum):
    UNVETTED = "UNVETTED"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    REJECTED_DD = "REJECTED_DD"
    EXPIRED = "EXPIRED"


class GrantStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COMPLIANCE_REVIEW = "COMPLIANCE_REVIEW"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    RETURNED = "RETURNED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class DisbursementSourceKind(str, Enum):
    GRANT = "GRANT"
    SCHOLARSHIP_AWARD = "SCHOLARSHIP_AWARD"


class SnapshotKind(str, Enum):
    QUARTER_END = "QUARTER_END"
    FISCAL_YEAR_END = "FISCAL_YEAR_END"


class ProgramStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    SCORING = "SCORING"
    AWARDED = "AWARDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MemberStatus(str, Enum):
    SEATED = "SEATED"
    RECUSED = "RECUSED"
    REMOVED = "REMOVED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_SCORING = "UNDER_SCORING"
    SELECTED = "SELECTED"
    NOT_SELECTED = "NOT_SELECTED"
    ACCEPTED_AWARD = "ACCEPTED_AWARD"
    DECLINED_AWARD = "DECLINED_AWARD"


class AwardStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DISBURSED = "DISBURSED"
    DECLINED = "DECLINED"
    FORFEITED = "FORFEITED"


class StatementStatus(str, Enum):
    GENERATED = "GENERATED"
    DELIVERED = "DELIVERED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# Ledger-style records carry only id + created_at (PRD §2.4).


class Fund(TypedDict, total=False):
    id: str
    fund_name: str
    fund_type: str
    status: str
    endowed: bool
    cash_balance: float
    invested_units: float
    invested_market_value: float
    total_market_value: float
    spendable_balance: float
    current_spending_allowance: float
    allowance_used: float
    inception_date: Optional[str]
    last_activity_at: Optional[str]
    inactivity_months: int
    created_at: str
    updated_at: str
    version: int


class FundAgreement(TypedDict, total=False):
    id: str
    fund_id: str
    agreement_version_no: int
    status: str
    spending_rate_pct: float
    spending_formula: str
    fee_tier_schedule: str
    successor_advisor_id: Optional[str]
    inactivity_trigger_months: int
    dormancy_trigger_months: int
    min_initial_contribution: float
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundAdvisor(TypedDict, total=False):
    id: str
    fund_id: str
    advisor_name: str
    email: str
    advisor_kind: str
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict, total=False):
    id: str
    fund_id: str
    donor_name: str
    asset_kind: str
    declared_value: float
    acceptance_status: str
    liquidation_status: str
    net_proceeds: Optional[float]
    gift_date: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetLot(TypedDict, total=False):
    # Ledger-style record: id + created_at only, no updated_at / version.
    id: str
    contribution_id: str
    description: str
    quantity: float
    appraised_value: float
    liquidation_fee_pct: float
    gross_proceeds: Optional[float]
    created_at: str


class InvestmentPool(TypedDict, total=False):
    id: str
    pool_name: str
    pool_kind: str
    status: str
    nav: float
    units_outstanding: float
    unit_price: float
    created_at: str
    updated_at: str
    version: int


class PoolHolding(TypedDict, total=False):
    id: str
    fund_id: str
    pool_id: str
    units_held: float
    created_at: str
    updated_at: str
    version: int


class UnitizationEvent(TypedDict, total=False):
    # Ledger-style record: id + created_at only.
    id: str
    pool_id: str
    event_kind: str
    fund_id: Optional[str]
    cash_amount: Optional[float]
    units_amount: Optional[float]
    new_nav: Optional[float]
    unit_price_applied: float
    units_delta: float
    created_at: str


class Grantee(TypedDict, total=False):
    id: str
    legal_name: str
    tax_id: str
    irs_subsection: str
    due_diligence_status: str
    cleared_at: Optional[str]
    expenditure_responsibility_required: bool
    created_at: str
    updated_at: str
    version: int


class GrantRecommendation(TypedDict, total=False):
    id: str
    fund_id: str
    grantee_id: str
    amount: float
    purpose: str
    recommended_by_advisor_id: Optional[str]
    status: str
    revision_count: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    # Ledger-style record: id + created_at only.
    id: str
    source_kind: str
    grant_id: Optional[str]
    award_id: Optional[str]
    fund_id: str
    amount: float
    created_at: str


class SpendingPolicyRun(TypedDict, total=False):
    # Ledger-style record: id + created_at only.
    id: str
    fiscal_year: int
    fund_id: str
    formula_used: str
    base_value: float
    allowance_granted: float
    market_values_used: List[float]
    created_at: str


class MarketValueSnapshot(TypedDict, total=False):
    # Ledger-style record: id + created_at only.
    id: str
    fund_id: str
    snapshot_kind: str
    effective_date: str
    market_value: float
    created_at: str


class FeeAssessment(TypedDict, total=False):
    # Ledger-style record: id + created_at only.
    id: str
    fund_id: str
    quarter_end_date: str
    quarter_end_balance: float
    schedule_used: str
    annual_fee: float
    quarterly_fee: float
    created_at: str


class ScholarshipProgram(TypedDict, total=False):
    id: str
    fund_id: str
    program_name: str
    status: str
    application_open: str
    application_close: str
    award_amount: float
    max_awards: int
    committee_size: int
    quorum_threshold: int
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict, total=False):
    id: str
    program_id: str
    member_name: str
    email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScholarshipApplication(TypedDict, total=False):
    id: str
    program_id: str
    applicant_name: str
    applicant_email: str
    status: str
    final_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class ScoreEntry(TypedDict, total=False):
    # Ledger-style record: id + created_at only.
    id: str
    application_id: str
    member_id: str
    academic: int
    financial_need: int
    essay: int
    interview: int
    weighted_score: float
    created_at: str


class ScholarshipAward(TypedDict, total=False):
    id: str
    application_id: str
    program_id: str
    fund_id: str
    amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class AnnualStatement(TypedDict, total=False):
    # Ledger-style record: id + created_at only.
    id: str
    fund_id: str
    fiscal_year: int
    opening_value: float
    contributions_total: float
    grants_total: float
    fees_total: float
    closing_value: float
    investment_gain_loss: float
    status: str
    created_at: str
