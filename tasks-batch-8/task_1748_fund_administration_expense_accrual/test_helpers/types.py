"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FUND_ACCOUNTANT = "FundAccountant"
    FUND_CONTROLLER = "FundController"
    PRICING_COMMITTEE = "PricingCommittee"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"


class DayCountConvention(str, Enum):
    ACT_365 = "ACT_365"
    ACT_360 = "ACT_360"


class DistributionFrequency(str, Enum):
    DAILY = "DAILY"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUALLY = "ANNUALLY"


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    FIXED_INCOME = "FIXED_INCOME"
    CASH_EQUIVALENT = "CASH_EQUIVALENT"
    DERIVATIVE = "DERIVATIVE"


class PricingLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class PriceSource(str, Enum):
    EXCHANGE_CLOSE = "EXCHANGE_CLOSE"
    PRICING_SERVICE = "PRICING_SERVICE"
    BROKER_QUOTE = "BROKER_QUOTE"
    FAIR_VALUE_COMMITTEE = "FAIR_VALUE_COMMITTEE"


class PriceObservationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    OVERRIDDEN = "OVERRIDDEN"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class NavRecordStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    FINAL = "FINAL"
    REOPENED = "REOPENED"


class PricingVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL_PRICED = "FINAL_PRICED"


class AccrualCategory(str, Enum):
    ADMIN_FEE = "ADMIN_FEE"
    CUSTODY_FEE = "CUSTODY_FEE"
    AUDIT_FEE = "AUDIT_FEE"
    LEGAL_FEE = "LEGAL_FEE"
    OTHER = "OTHER"


class AccrualStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    POSTED = "POSTED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class LedgerEntryType(str, Enum):
    WAIVER = "WAIVER"
    RECOUPMENT = "RECOUPMENT"


class DistributionStatus(str, Enum):
    DECLARED = "DECLARED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class BreakType(str, Enum):
    CUSTODIAN_POSITION = "CUSTODIAN_POSITION"
    BROKER_POSITION = "BROKER_POSITION"


class BreakStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class ResolutionType(str, Enum):
    NO_CHANGE = "NO_CHANGE"
    ADJUST_POSITION = "ADJUST_POSITION"


class FeeType(str, Enum):
    ADVISER = "ADVISER"
    ADMINISTRATOR = "ADMINISTRATOR"


class FeeInvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"


class FilingType(str, Enum):
    N_PORT = "N_PORT"
    N_CEN = "N_CEN"
    ANNUAL_REPORT = "ANNUAL_REPORT"
    SEMI_ANNUAL_REPORT = "SEMI_ANNUAL_REPORT"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    FILED = "FILED"
    AMENDED = "AMENDED"


class CapitalActivityType(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    REDEMPTION = "REDEMPTION"
    INCOME_POSTING = "INCOME_POSTING"


# --- Entity TypedDicts -------------------------------------------------------
# All primary resources carry id/created_at/updated_at/version (PRD §2.5);
# the waiver ledger entry is the single exception (id + created_at only).


class Fund(TypedDict):
    id: str
    fund_name: str
    ticker: str
    base_currency: str
    fiscal_year_end: str
    adviser_name: str
    admin_fee_bps: float
    adviser_fee_tiers: List[dict]
    day_count_convention: str
    last_closed_fiscal_year_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShareClass(TypedDict):
    id: str
    fund_id: str
    class_ticker: str
    distribution_frequency: str
    shares_outstanding: float
    retained_income: float
    created_at: str
    updated_at: str
    version: int


class Security(TypedDict):
    id: str
    security_identifier: str
    description: str
    asset_class: str
    default_pricing_level: str
    currency: str
    created_at: str
    updated_at: str
    version: int


class Position(TypedDict):
    id: str
    share_class_id: str
    security_id: str
    quantity: float
    cost_basis_total: float
    opened_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceObservation(TypedDict):
    id: str
    security_id: str
    price_date: str
    price: float
    source: str
    pricing_level: str
    is_fair_value_override: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class NavRecord(TypedDict):
    id: str
    share_class_id: str
    accounting_date: str
    status: str
    pricing_variant_used: str
    gross_asset_value: float
    expense_accrual_total: float
    total_net_assets: float
    nav_per_share: float
    provisional_nav_per_share: Optional[float]
    final_nav_per_share: Optional[float]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class ExpenseAccrual(TypedDict):
    id: str
    share_class_id: str
    accrual_date: str
    category: str
    annual_rate_bps: float
    base_net_assets: float
    accrued_amount: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WaiverAgreement(TypedDict):
    id: str
    share_class_id: str
    cap_bps: float
    effective_from: str
    effective_to: str
    recovery_window_months: int
    status: str
    recoverable_balance: float
    created_at: str
    updated_at: str
    version: int


class WaiverLedgerEntry(TypedDict):
    # Append-only ledger row: carries ONLY id + created_at (PRD §2.5).
    id: str
    waiver_agreement_id: str
    entry_type: str
    amount: float
    entry_date: str
    expires_at: Optional[str]
    remaining_amount: float
    created_at: str


class Distribution(TypedDict):
    id: str
    share_class_id: str
    declaration_date: str
    ex_date: str
    record_date: str
    payable_date: str
    distributable_amount: float
    shares_snapshot: float
    income_per_share: float
    total_amount: float
    status: str
    reinvested_shares: Optional[float]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconciliationBreak(TypedDict):
    id: str
    fund_id: str
    position_id: str
    break_type: str
    break_date: str
    counterparty_quantity: float
    book_quantity: float
    variance: float
    resolution_type: Optional[str]
    prior_book_quantity: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeeInvoice(TypedDict):
    id: str
    fund_id: str
    fee_type: str
    period_start: str
    period_end: str
    average_daily_net_assets: float
    gross_fee: float
    waiver_offset: float
    net_fee: float
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RegulatoryFiling(TypedDict):
    id: str
    fund_id: str
    filing_type: str
    period_end: str
    filing_deadline: str
    status: str
    filed_at: Optional[str]
    filed_after_deadline: bool
    prepared_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
