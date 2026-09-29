"""Domain types for the mutual fund transfer agency API.

Entity TypedDicts, status enums and the desk-role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    TRANSFER_AGENT_OPERATOR = "TransferAgentOperator"
    FUND_ACCOUNTANT = "FundAccountant"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    DEALER_OPERATIONS = "DealerOperations"
    ACCOUNT_HOLDER = "AccountHolder"


# --------------------------------------------------------------------------- enums
class FundStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED_TO_NEW = "CLOSED_TO_NEW"


class ClassCode(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    I = "I"


class RegistrationType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    JOINT_TENANTS = "JOINT_TENANTS"
    UGMA_UTMA = "UGMA_UTMA"
    IRA_TRADITIONAL = "IRA_TRADITIONAL"
    ROTH_IRA = "ROTH_IRA"
    TRUST = "TRUST"
    CORPORATE = "CORPORATE"


class AccountChannel(str, Enum):
    DIRECT = "DIRECT"
    NETWORKED = "NETWORKED"
    OMNIBUS = "OMNIBUS"


class DividendOption(str, Enum):
    CASH = "CASH"
    REINVEST = "REINVEST"


class AccountStatus(str, Enum):
    PENDING_DOCS = "PENDING_DOCS"
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class HouseholdBasisVariant(str, Enum):
    MARKET_VALUE_BASIS = "MARKET_VALUE_BASIS"
    HISTORICAL_COST_BASIS = "HISTORICAL_COST_BASIS"


class NavRecordStatus(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"
    UNDER_ERROR_REVIEW = "UNDER_ERROR_REVIEW"
    CORRECTED = "CORRECTED"
    STALE_REPRICE_REQUIRED = "STALE_REPRICE_REQUIRED"


class TradeType(str, Enum):
    PURCHASE = "PURCHASE"
    REDEMPTION = "REDEMPTION"
    EXCHANGE = "EXCHANGE"
    REINVESTMENT = "REINVESTMENT"


class ExecutionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PENDING_AS_OF_APPROVAL = "PENDING_AS_OF_APPROVAL"
    PRICED_PROVISIONAL = "PRICED_PROVISIONAL"
    PRICED_FINAL = "PRICED_FINAL"
    RESTATED = "RESTATED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class PricingVariant(str, Enum):
    PRELIMINARY_NAV = "PRELIMINARY_NAV"
    FINAL_NAV = "FINAL_NAV"


class DistributionType(str, Enum):
    ORDINARY_INCOME = "ORDINARY_INCOME"
    SHORT_TERM_CAPITAL_GAIN = "SHORT_TERM_CAPITAL_GAIN"
    LONG_TERM_CAPITAL_GAIN = "LONG_TERM_CAPITAL_GAIN"


class DistributionStatus(str, Enum):
    DECLARED = "DECLARED"
    RECORDED = "RECORDED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REVERSED = "REVERSED"


class PlanType(str, Enum):
    SYSTEMATIC_INVESTMENT = "SYSTEMATIC_INVESTMENT"
    SYSTEMATIC_WITHDRAWAL = "SYSTEMATIC_WITHDRAWAL"
    SYSTEMATIC_EXCHANGE = "SYSTEMATIC_EXCHANGE"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PlanFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class SuspensionReason(str, Enum):
    OPERATOR_REQUEST = "OPERATOR_REQUEST"
    ACCOUNT_RESTRICTED = "ACCOUNT_RESTRICTED"
    INSUFFICIENT_POSITION_VALUE = "INSUFFICIENT_POSITION_VALUE"


class BlueSkyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class CaseStatus(str, Enum):
    DETECTED = "DETECTED"
    ASSESSED = "ASSESSED"
    IMMATERIAL_CLOSED = "IMMATERIAL_CLOSED"
    MATERIAL_APPROVED = "MATERIAL_APPROVED"
    REPROCESSED = "REPROCESSED"
    SUPERSEDED = "SUPERSEDED"


class Materiality(str, Enum):
    MATERIAL = "MATERIAL"
    IMMATERIAL = "IMMATERIAL"


class ReconciliationStatus(str, Enum):
    MATCHED = "MATCHED"
    BREAK_IDENTIFIED = "BREAK_IDENTIFIED"
    RESOLVED = "RESOLVED"
    DISPUTED = "DISPUTED"


class LedgerEntryReason(str, Enum):
    PURCHASE_SETTLEMENT = "PURCHASE_SETTLEMENT"
    REDEMPTION_SETTLEMENT = "REDEMPTION_SETTLEMENT"
    EXCHANGE_OUT = "EXCHANGE_OUT"
    EXCHANGE_IN = "EXCHANGE_IN"
    DIVIDEND_REINVESTMENT = "DIVIDEND_REINVESTMENT"
    NAV_CORRECTION_RESTATEMENT = "NAV_CORRECTION_RESTATEMENT"
    TRADE_REVERSAL = "TRADE_REVERSAL"
    DISTRIBUTION_REVERSAL = "DISTRIBUTION_REVERSAL"


# ------------------------------------------------------------------- entity shapes
class BreakpointTier(TypedDict):
    min_qualifying_amount: float
    load_pct: float


class Fund(TypedDict):
    id: str
    name: str
    fund_family_code: str
    cutoff_time_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShareClass(TypedDict):
    id: str
    fund_id: str
    class_code: str
    seed_nav_per_share: float
    breakpoint_tiers: List[BreakpointTier]
    cdsc_enabled: bool
    twelve_b_one_fee_pct: float
    total_shares_outstanding: float
    created_at: str
    updated_at: str
    version: int


class ShareholderAccount(TypedDict):
    id: str
    registration_type: str
    account_channel: str
    state_code: str
    tax_id: str
    primary_owner_name: str
    dealer_firm_code: Optional[str]
    dividend_option: str
    linked_primary_account_id: Optional[str]
    tin_certified: bool
    status: str
    restriction_reason: Optional[str]
    household_basis_amount: float
    household_basis_variant: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict):
    id: str
    account_id: str
    share_class_id: str
    shares: float
    cost_basis_amount: float
    reinvested_shares: float
    avg_cost_per_share: float
    first_purchase_date: Optional[str]
    current_roa_tier_pct: float
    market_value_amount: float
    created_at: str
    updated_at: str
    version: int


class NavRecord(TypedDict):
    id: str
    share_class_id: str
    valuation_date: str
    total_net_assets: float
    shares_outstanding_snapshot: float
    nav_per_share: float
    original_nav_per_share: Optional[float]
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Trade(TypedDict):
    id: str
    account_id: str
    share_class_id: str
    exchange_target_share_class_id: Optional[str]
    parent_distribution_id: Optional[str]
    originating_plan_id: Optional[str]
    blue_sky_registration_id: Optional[str]
    trade_type: str
    gross_amount: Optional[float]
    shares_requested: Optional[float]
    as_of_date: Optional[str]
    dealer_reference: Optional[str]
    received_at: str
    trade_date: str
    execution_status: str
    settlement_status: str
    pricing_variant: Optional[str]
    nav_per_share_applied: Optional[float]
    roa_qualifying_amount: Optional[float]
    roa_basis_variant: Optional[str]
    sales_load_pct: Optional[float]
    sales_load_amount: Optional[float]
    net_invested_amount: Optional[float]
    shares_transacted: Optional[float]
    gross_proceeds_amount: Optional[float]
    cdsc_amount: Optional[float]
    net_proceeds_amount: Optional[float]
    exchange_target_shares: Optional[float]
    restated_share_delta: Optional[float]
    captured_by_user_id: str
    approved_by_user_id: Optional[str]
    cancel_reason: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    share_class_id: str
    distribution_type: str
    rate_per_share: float
    record_date: str
    ex_date: str
    pay_date: str
    status: str
    payment_count: int
    total_gross_amount: float
    total_withholding_amount: float
    total_cash_amount: float
    total_reinvested_amount: float
    reinvest_nav_per_share: Optional[float]
    created_at: str
    updated_at: str
    version: int


class DistributionPayment(TypedDict):
    id: str
    distribution_id: str
    account_id: str
    position_id: str
    reinvestment_trade_id: Optional[str]
    shares_of_record: float
    gross_amount: float
    withholding_amount: float
    net_amount: float
    cash_amount: float
    reinvested_shares: float
    payout_option: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SystematicPlan(TypedDict):
    id: str
    account_id: str
    source_share_class_id: str
    target_share_class_id: Optional[str]
    plan_type: str
    amount: float
    frequency: str
    next_run_date: str
    status: str
    executed_count: int
    last_run_date: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlueSkyRegistration(TypedDict):
    id: str
    share_class_id: str
    state_code: str
    registered_amount: float
    effective_date: str
    expiration_date: str
    reserved_amount: float
    consumed_amount: float
    remaining_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PricingErrorCase(TypedDict):
    id: str
    nav_record_id: str
    corrected_nav_per_share: float
    error_reason: str
    original_nav_per_share: float
    error_bps: Optional[float]
    materiality: Optional[str]
    status: str
    detected_by_user_id: str
    approved_by_user_id: Optional[str]
    reprocessed_by_user_id: Optional[str]
    restated_trade_count: int
    invalidated_nav_record_count: int
    created_at: str
    updated_at: str
    version: int


class OmnibusReconciliation(TypedDict):
    id: str
    account_id: str
    as_of_date: str
    dealer_reported_purchase_amount: float
    dealer_reported_redemption_amount: float
    dealer_reported_net_shares: float
    ta_purchase_amount: float
    ta_redemption_amount: float
    ta_net_shares: float
    break_amount: float
    tolerance_amount: float
    status: str
    adjustment_trade_id: Optional[str]
    resolution_note: Optional[str]
    dispute_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShareLedgerEntry(TypedDict):
    """The share ledger is append-only: an entry carries only id and created_at
    besides its own fields — no updated_at and no version."""

    id: str
    position_id: str
    trade_id: Optional[str]
    share_delta: float
    entry_reason: str
    effective_date: str
    resulting_share_balance: float
    created_at: str
