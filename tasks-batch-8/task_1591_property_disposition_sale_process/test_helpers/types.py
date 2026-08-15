"""Domain types: entity TypedDicts, status enums, role enum.

All twelve primary resources carry the standard system-managed fields
(id, created_at, updated_at, version) described in PRD "Common Resource
Properties".
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    DISPOSITION_MANAGER = "DispositionManager"
    ASSET_ANALYST = "AssetAnalyst"
    INVESTMENT_COMMITTEE = "InvestmentCommittee"
    BROKER = "Broker"
    BUYER = "Buyer"
    CLOSING_OFFICER = "ClosingOfficer"
    LOAN_SERVICER = "LoanServicer"


class MarketingStatus(str, Enum):
    EVALUATION = "EVALUATION"
    LISTED = "LISTED"
    OFFERS_OPEN = "OFFERS_OPEN"
    OFFERS_CLOSED = "OFFERS_CLOSED"
    WITHDRAWN = "WITHDRAWN"


class DealStatus(str, Enum):
    IDLE = "IDLE"
    PSA_DRAFT = "PSA_DRAFT"
    PSA_EXECUTED = "PSA_EXECUTED"
    DD_ACTIVE = "DD_ACTIVE"
    BINDING = "BINDING"
    CLOSING = "CLOSING"
    SOLD = "SOLD"


class AssetType(str, Enum):
    OFFICE = "OFFICE"
    INDUSTRIAL = "INDUSTRIAL"
    RETAIL = "RETAIL"
    MULTIFAMILY = "MULTIFAMILY"


class PrepaymentType(str, Enum):
    NONE = "NONE"
    STEP_DOWN = "STEP_DOWN"
    YIELD_MAINTENANCE = "YIELD_MAINTENANCE"


class AnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class Recommendation(str, Enum):
    SELL = "SELL"
    HOLD = "HOLD"
    MARGINAL = "MARGINAL"


class EngagementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"
    COMPLETED = "COMPLETED"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    IN_REVIEW = "IN_REVIEW"


class QualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    SELECTED = "SELECTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PsaStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    DD_ACTIVE = "DD_ACTIVE"
    BINDING = "BINDING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"
    SUPERSEDED = "SUPERSEDED"


class DepositStatus(str, Enum):
    DUE = "DUE"
    POSTED = "POSTED"
    DELINQUENT = "DELINQUENT"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"
    APPLIED = "APPLIED"


class DdItemStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CONTESTED = "CONTESTED"
    WITHDRAWN = "WITHDRAWN"
    RESCINDED = "RESCINDED"


class PayoffStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    STALE = "STALE"
    SETTLED = "SETTLED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    STALE = "STALE"
    FINALIZED = "FINALIZED"


class EscrowStatus(str, Enum):
    HELD = "HELD"
    PARTIALLY_RELEASED = "PARTIALLY_RELEASED"
    RELEASED = "RELEASED"


class Asset(TypedDict, total=False):
    id: str
    name: str
    market: str
    asset_type: str
    noi_cents: int
    noi_growth_bps: int
    book_value_cents: int
    guidance_price_cents: int
    loan_balance_cents: int
    loan_rate_bps: int
    loan_maturity_date: Optional[str]
    monthly_debt_service_cents: int
    remaining_term_months: int
    prepayment_type: str
    prepayment_lockout_until: Optional[str]
    defeasance_allowed: bool
    defeasance_fee_cents: int
    marketing_status: str
    deal_status: str
    offers_deadline: Optional[str]
    last_campaign_closed_at: Optional[str]
    forfeited_deposits_cents: int
    final_sale_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class HoldSellAnalysis(TypedDict, total=False):
    id: str
    asset_id: str
    cap_rate_bps: int
    discount_rate_bps: int
    exit_cap_rate_bps: int
    hold_years: int
    selected_method: str
    est_sale_price_cents: int
    est_selling_costs_cents: int
    hold_value_direct_cap_cents: int
    hold_value_dcf_cents: int
    hold_value_cents: int
    sell_net_cents: int
    value_gap_cents: int
    recommendation: str
    status: str
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrokerEngagement(TypedDict, total=False):
    id: str
    asset_id: str
    broker_firm_name: str
    broker_user_id: str
    window_start: str
    window_end: str
    commission_provisional_cents: Optional[int]
    commission_final_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class OfferingPackage(TypedDict, total=False):
    id: str
    asset_id: str
    documents: List[dict]
    verified_categories_count: int
    completeness_pct: int
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bidder(TypedDict, total=False):
    id: str
    asset_id: str
    organization_name: str
    proof_of_funds_cents: int
    qualification_status: str
    access_windows: List[dict]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    asset_id: str
    bidder_id: str
    price_cents: int
    deposit_cents: int
    dd_period_days: int
    closing_period_days: int
    status: str
    improvement_count: int
    created_at: str
    updated_at: str
    version: int


class PurchaseAgreement(TypedDict, total=False):
    id: str
    asset_id: str
    bid_id: str
    proration_convention: str
    buyer_bidder_id: str
    price_cents: int
    original_price_cents: int
    executed_at: Optional[str]
    dd_deadline: Optional[str]
    closing_date: Optional[str]
    initial_deposit_cents: int
    additional_deposit_cents: int
    accepted_retrade_total_cents: int
    termination_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    psa_id: str
    kind: str
    amount_cents: int
    due_date: str
    posted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DueDiligenceItem(TypedDict, total=False):
    id: str
    psa_id: str
    category: str
    description: str
    requested_reduction_cents: int
    accepted_reduction_cents: Optional[int]
    filed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanPayoff(TypedDict, total=False):
    id: str
    asset_id: str
    method: str
    reinvestment_rate_bps: int
    accrued_days: int
    anticipated_settlement_date: str
    quoted_at: str
    quote_expires_at: str
    accrued_interest_cents: int
    prepayment_penalty_cents: int
    defeasance_cost_cents: int
    total_estimated_cost_cents: int
    final_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosingStatement(TypedDict, total=False):
    id: str
    psa_id: str
    convention: str
    closing_date: str
    property_tax_annual_cents: int
    tax_period_start: str
    rent_monthly_cents: int
    cam_annual_cents: int
    proration_buyer_credit_cents: int
    proration_buyer_debit_cents: int
    deposits_applied_cents: int
    commission_cents: int
    payoff_total_cents: int
    holdback_cents: int
    buyer_due_cents: int
    seller_net_cents: int
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowHoldback(TypedDict, total=False):
    id: str
    psa_id: str
    purpose: str
    amount_cents: int
    available_cents: int
    released_to_seller_cents: int
    paid_to_claims_cents: int
    release_date: str
    claims: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int
