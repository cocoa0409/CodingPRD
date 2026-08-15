"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class FundSuspensionStatus(str, Enum):
    NOT_SUSPENDED = "NOT_SUSPENDED"
    SUSPENDED = "SUSPENDED"


class RedemptionFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    ANNUAL = "ANNUAL"


class NavPeriodStatus(str, Enum):
    OPEN = "OPEN"
    NAV_FINALIZED = "NAV_FINALIZED"
    CLOSED = "CLOSED"


class SeriesStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    ROLLED = "ROLLED"


class InvestorType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    JOINT = "JOINT"
    CORPORATION = "CORPORATION"
    TRUST = "TRUST"
    PARTNERSHIP = "PARTNERSHIP"
    LLC = "LLC"
    EMPLOYEE_BENEFIT_PLAN = "EMPLOYEE_BENEFIT_PLAN"


class KycStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DOCUMENTS_PENDING = "DOCUMENTS_PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AccreditationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ACCREDITED = "ACCREDITED"
    QUALIFIED_PURCHASER = "QUALIFIED_PURCHASER"
    EXPIRED = "EXPIRED"


class KycRiskRating(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    PROHIBITED = "PROHIBITED"


class KycCaseStatus(str, Enum):
    OPEN = "OPEN"
    AWAITING_DOCUMENTS = "AWAITING_DOCUMENTS"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ESCALATED = "ESCALATED"


class AttestationTier(str, Enum):
    ACCREDITED = "ACCREDITED"
    QUALIFIED_PURCHASER = "QUALIFIED_PURCHASER"


class EvidenceType(str, Enum):
    INCOME_STATEMENT = "INCOME_STATEMENT"
    NET_WORTH_CERT = "NET_WORTH_CERT"
    CPA_LETTER = "CPA_LETTER"
    LICENSED_PROFESSIONAL = "LICENSED_PROFESSIONAL"
    ENTITY_ASSETS = "ENTITY_ASSETS"


class AttestationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SubscriptionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    KYC_HOLD = "KYC_HOLD"
    COMPLIANCE_APPROVED = "COMPLIANCE_APPROVED"
    FUNDING_PARTIAL = "FUNDING_PARTIAL"
    FUNDED = "FUNDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class SideLetterStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class MfnClauseTag(str, Enum):
    FEE_REBATE = "FEE_REBATE"
    LIQUIDITY = "LIQUIDITY"
    INFORMATION_RIGHTS = "INFORMATION_RIGHTS"
    CAPACITY_RIGHTS = "CAPACITY_RIGHTS"
    CO_INVEST = "CO_INVEST"


class MfnClauseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CapitalAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REDEMPTION_PENDING = "REDEMPTION_PENDING"
    CLOSED = "CLOSED"


class SeriesLotStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
    FULLY_REDEEMED = "FULLY_REDEEMED"
    ROLLED = "ROLLED"


class RedemptionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    PARTIALLY_APPROVED = "PARTIALLY_APPROVED"
    DEFERRED = "DEFERRED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DELIVERED = "DELIVERED"


class UserRole(str, Enum):
    FUND_ADMIN = "FundAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TRANSFER_AGENT = "TransferAgent"
    PORTFOLIO_MANAGER = "PortfolioManager"
    INVESTOR = "Investor"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry common_fields: true)
# ---------------------------------------------------------------------------

class Fund(TypedDict, total=False):
    id: str
    fund_name: str
    domicile: str
    gate_threshold_pct: float
    lockup_months_default: int
    notice_days_default: int
    fiscal_year_end_month: int
    suspension_status: str
    current_nav_period_id: Optional[str]
    total_net_assets_cents: int
    created_at: str
    updated_at: str
    version: int


class ShareClass(TypedDict, total=False):
    id: str
    fund_id: str
    class_code: str
    min_initial_investment_cents: int
    min_additional_investment_cents: int
    management_fee_bps: int
    performance_fee_bps: int
    hurdle_rate_bps: int
    high_water_mark_required: bool
    lockup_months: int
    notice_days: int
    redemption_frequency: str
    is_open_for_subscription: bool
    is_open_for_redemption: bool
    created_at: str
    updated_at: str
    version: int


class NavPeriod(TypedDict, total=False):
    id: str
    fund_id: str
    period_index: int
    period_start_utc: str
    period_end_utc: str
    gross_return_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Series(TypedDict, total=False):
    id: str
    share_class_id: str
    nav_period_id: str
    series_index: int
    opening_nav_per_share_cents: int
    equalization_factor_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict, total=False):
    id: str
    legal_name: str
    investor_type: str
    tax_id: str
    email: str
    residence_country: str
    is_us_person: bool
    kyc_status: str
    accreditation_status: str
    aggregate_unfunded_commitment_cents: int
    created_at: str
    updated_at: str
    version: int


class KycCase(TypedDict, total=False):
    id: str
    investor_id: str
    case_sequence: int
    risk_rating: str
    required_documents: List[str]
    submitted_documents: List[str]
    pep_hit: bool
    sanctions_hit: bool
    adverse_media_hit: bool
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccreditationAttestation(TypedDict, total=False):
    id: str
    investor_id: str
    attestation_tier: str
    evidence_type: str
    evidence_document_id: str
    attested_at_utc: str
    expires_at_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    investor_id: str
    share_class_id: str
    commitment_amount_cents: int
    funded_amount_cents: int
    funding_deadline_utc: str
    late_fees_accrued_cents: int
    effective_series_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SideLetter(TypedDict, total=False):
    id: str
    subscription_id: str
    investor_id: str
    share_class_id: str
    terms_document_id: str
    supersedes_side_letter_id: Optional[str]
    mfn_election_active: bool
    elected_clause_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MfnClause(TypedDict, total=False):
    id: str
    fund_id: str
    clause_tag: str
    clause_text: str
    capacity_threshold_cents: int
    fee_rebate_bps: int
    notice_days_reduction: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CapitalAccount(TypedDict, total=False):
    id: str
    investor_id: str
    share_class_id: str
    subscription_id: str
    current_balance_cents: int
    high_water_mark_cents: int
    accrued_performance_fee_cents: int
    equalization_deposit_cents: int
    locked_until_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SeriesLot(TypedDict, total=False):
    id: str
    capital_account_id: str
    series_id: str
    nav_period_id: str
    shares: float
    cost_basis_cents: int
    current_value_cents: int
    equalization_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RedemptionRequest(TypedDict, total=False):
    id: str
    capital_account_id: str
    investor_id: str
    requested_amount_cents: int
    requested_shares: Optional[float]
    notice_given_at_utc: str
    requested_effective_period_id: str
    effective_period_id: Optional[str]
    gate_applied_pct: float
    settled_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InvestorStatement(TypedDict, total=False):
    id: str
    capital_account_id: str
    nav_period_id: str
    opening_balance_cents: int
    closing_balance_cents: int
    contributions_cents: int
    distributions_cents: int
    management_fee_cents: int
    performance_fee_cents: int
    delivered_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
