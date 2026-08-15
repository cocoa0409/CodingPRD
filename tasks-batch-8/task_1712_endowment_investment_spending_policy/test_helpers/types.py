"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ENDOWMENT_ADMIN = "EndowmentAdmin"
    INVESTMENT_OFFICER = "InvestmentOfficer"
    DEVELOPMENT_OFFICER = "DevelopmentOfficer"
    BOARD_MEMBER = "BoardMember"
    PROGRAM_MANAGER = "ProgramManager"


class PoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ValuationStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class DonorType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FOUNDATION = "FOUNDATION"
    CORPORATION = "CORPORATION"
    ESTATE = "ESTATE"


class EndowmentClass(str, Enum):
    TRUE_ENDOWMENT = "TRUE_ENDOWMENT"
    QUASI_ENDOWMENT = "QUASI_ENDOWMENT"
    TERM_ENDOWMENT = "TERM_ENDOWMENT"


class PurposeRestriction(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    SCHOLARSHIP = "SCHOLARSHIP"
    PROFESSORSHIP = "PROFESSORSHIP"
    RESEARCH = "RESEARCH"
    CAPITAL_PROJECTS = "CAPITAL_PROJECTS"


class FundStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class SpendingPosture(str, Enum):
    NORMAL = "NORMAL"
    SPENDING_SUSPENDED = "SPENDING_SUSPENDED"
    EXCEPTION_ACTIVE = "EXCEPTION_ACTIVE"


class GiftType(str, Enum):
    CORPUS = "CORPUS"
    EXPENDABLE = "EXPENDABLE"


class GiftStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    UNITIZED = "UNITIZED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class DistributionStatus(str, Enum):
    PROJECTED = "PROJECTED"
    PROPOSED = "PROPOSED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DISTRIBUTED = "DISTRIBUTED"
    CANCELLED = "CANCELLED"


class ExceptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ENDORSED = "ENDORSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXERCISED = "EXERCISED"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"


class PayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISBURSED = "DISBURSED"
    CLOSED_FULLY_SPENT = "CLOSED_FULLY_SPENT"
    CLOSED_RETURNED = "CLOSED_RETURNED"


class AssetClass(str, Enum):
    US_EQUITY = "US_EQUITY"
    DEVELOPED_INTL_EQUITY = "DEVELOPED_INTL_EQUITY"
    EMERGING_MARKETS = "EMERGING_MARKETS"
    FIXED_INCOME = "FIXED_INCOME"
    REAL_ASSETS = "REAL_ASSETS"
    PRIVATE_EQUITY = "PRIVATE_EQUITY"
    CASH = "CASH"


class DriftStatus(str, Enum):
    IN_BAND = "IN_BAND"
    BREACHED = "BREACHED"


class EngagementStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ENGAGED = "ENGAGED"
    WATCHLIST = "WATCHLIST"
    PROBATION = "PROBATION"
    TERMINATED = "TERMINATED"
    DECLINED = "DECLINED"


class ReportType(str, Enum):
    DONOR_FUND = "DONOR_FUND"
    BOARD_INVESTMENT = "BOARD_INVESTMENT"
    SPENDING_COMPLIANCE = "SPENDING_COMPLIANCE"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    PUBLISHED = "PUBLISHED"


class LedgerEntryType(str, Enum):
    GIFT_UNITIZE = "GIFT_UNITIZE"
    REINVEST_UNITIZE = "REINVEST_UNITIZE"
    DISTRIBUTION_REDEEM = "DISTRIBUTION_REDEEM"
    CORPUS_REDEEM = "CORPUS_REDEEM"


class EndowmentPool(TypedDict, total=False):
    id: str
    pool_name: str
    inception_fiscal_year: int
    pool_status: str
    current_quarter_index: int
    current_unit_price_millicents: int
    total_units_outstanding_micro: int
    total_market_value_cents: int
    created_at: str
    updated_at: str
    version: int


class SpendingPolicyVersion(TypedDict, total=False):
    id: str
    pool_id: str
    spending_rate_bps: int
    smoothing_window_quarters: int
    band_floor_bps: int
    band_cap_bps: int
    effective_from_fiscal_year: int
    policy_status: str
    proposed_by_user_id: str
    adopted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnitValuation(TypedDict, total=False):
    id: str
    pool_id: str
    quarter_index: int
    valuation_status: str
    estimated_pool_market_value_cents: int
    final_pool_market_value_cents: Optional[int]
    preliminary_unit_price_millicents: int
    final_unit_price_millicents: Optional[int]
    created_by_user_id: str
    finalized_by_user_id: Optional[str]
    supersedes_valuation_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict, total=False):
    id: str
    donor_name: str
    donor_type: str
    contact_email: Optional[str]
    total_contributed_cents: int
    created_at: str
    updated_at: str
    version: int


class Fund(TypedDict, total=False):
    id: str
    pool_id: str
    fund_code: str
    fund_name: str
    endowment_class: str
    term_end_quarter_index: Optional[int]
    purpose_restriction: str
    fund_status: str
    spending_posture: str
    historic_gift_value_cents: int
    pledged_corpus_cents: int
    units_held_micro: int
    market_value_cents: int
    is_underwater: bool
    activated_quarter_index: Optional[int]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class GiftContribution(TypedDict, total=False):
    id: str
    fund_id: str
    donor_id: Optional[str]
    external_ref: str
    gift_type: str
    amount_cents: int
    gift_status: str
    received_quarter_index: Optional[int]
    provisional_units_estimate_micro: Optional[int]
    unitized_quarter_index: Optional[int]
    units_purchased_micro: Optional[int]
    source_payout_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpendingDistribution(TypedDict, total=False):
    id: str
    fund_id: str
    fiscal_year: int
    distribution_status: str
    policy_id: str
    smoothed_base_cents: int
    raw_amount_cents: int
    prior_year_distribution_cents: Optional[int]
    band_adjusted_amount_cents: int
    was_underwater_at_proposal: bool
    applied_exception_id: Optional[str]
    final_amount_cents: int
    distributed_amount_cents: int
    units_redeemed_micro: Optional[int]
    proposed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PolicyException(TypedDict, total=False):
    id: str
    fund_id: str
    fiscal_year: int
    requested_amount_cents: int
    justification: str
    exception_status: str
    approved_amount_cents: Optional[int]
    requested_by_user_id: str
    endorsed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramPayout(TypedDict, total=False):
    id: str
    distribution_id: str
    program_code: str
    program_purpose: str
    allocated_amount_cents: int
    payout_status: str
    disbursed_quarter_index: Optional[int]
    spent_amount_cents: int
    unspent_amount_cents: int
    swept_gift_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssetClassAllocation(TypedDict, total=False):
    id: str
    pool_id: str
    asset_class: str
    target_pct_bps: int
    rebalance_band_bps: int
    actual_pct_bps: int
    drift_status: str
    drift_acknowledged: bool
    created_at: str
    updated_at: str
    version: int


class InvestmentManager(TypedDict, total=False):
    id: str
    pool_id: str
    manager_name: str
    asset_class: str
    benchmark_code: str
    coverage_start_quarter: int
    coverage_end_quarter: Optional[int]
    engagement_status: str
    neg_excess_streak: int
    nonneg_excess_streak: int
    created_at: str
    updated_at: str
    version: int


class ManagerQuarterReport(TypedDict, total=False):
    id: str
    manager_id: str
    quarter_index: int
    beginning_mv_cents: int
    ending_mv_cents: int
    flows: list
    benchmark_return_bps: int
    return_bps: int
    simple_return_bps: int
    excess_bps: int
    created_at: str
    updated_at: str
    version: int


class AnnualReport(TypedDict, total=False):
    id: str
    pool_id: str
    fund_id: Optional[str]
    report_type: str
    fiscal_year: int
    report_status: str
    created_by_user_id: str
    published_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnitLedgerEntry(TypedDict, total=False):
    # Append-only entity (PRD §2.4): carries id and created_at ONLY.
    # updated_at and version are absent by contract — do not add them here.
    id: str
    fund_id: str
    quarter_index: int
    entry_type: str
    units_delta_micro: int
    amount_cents: int
    reference_id: str
    created_at: str
