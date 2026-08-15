"""Domain types: entity TypedDicts, status enums, role enum.

Money is integer cents; rates/margins/haircuts are integer basis points.
The logical clock starts at exactly 2026-08-01T00:00:00Z.
"""
from enum import Enum
from typing import Optional, TypedDict


class SecurityStatus(str, Enum):
    LENDABLE = "LENDABLE"
    HALTED = "HALTED"


class AssetClass(str, Enum):
    EQUITY = "EQUITY"
    GOV_BOND = "GOV_BOND"
    CORP_BOND = "CORP_BOND"


class OwnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DEFAULTED = "DEFAULTED"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"


class BorrowRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    MATCHED = "MATCHED"
    LOANED = "LOANED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CollateralType(str, Enum):
    CASH = "CASH"
    SECURITIES = "SECURITIES"


class LoanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    BOOKED = "BOOKED"
    RECALLED = "RECALLED"
    SETTLED = "SETTLED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class MarginStatus(str, Enum):
    CURRENT = "CURRENT"
    CALL_OPEN = "CALL_OPEN"


class PledgeType(str, Enum):
    CASH = "CASH"
    SECURITY = "SECURITY"


class PledgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    SUBSTITUTED = "SUBSTITUTED"
    SEIZED = "SEIZED"


class MarginCallStatus(str, Enum):
    OPEN = "OPEN"
    CURED = "CURED"
    ESCALATED = "ESCALATED"
    DEFAULTED = "DEFAULTED"


class RecallStatus(str, Enum):
    ISSUED = "ISSUED"
    EXTENDED = "EXTENDED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BOUGHT_IN = "BOUGHT_IN"
    CANCELLED = "CANCELLED"


class RecallReason(str, Enum):
    SALE = "SALE"
    CORPORATE_ACTION = "CORPORATE_ACTION"
    VOTE = "VOTE"
    PORTFOLIO_REBALANCE = "PORTFOLIO_REBALANCE"


class InstrumentType(str, Enum):
    MMF = "MMF"
    REPO = "REPO"
    TIME_DEPOSIT = "TIME_DEPOSIT"


class TrancheStatus(str, Enum):
    INVESTED = "INVESTED"
    UNWOUND = "UNWOUND"


class LedgerEntryType(str, Enum):
    FEE_ACCRUAL_PROVISIONAL = "FEE_ACCRUAL_PROVISIONAL"
    FEE_ACCRUAL_FINAL = "FEE_ACCRUAL_FINAL"
    FEE_TRUE_UP = "FEE_TRUE_UP"
    REBATE_ACCRUAL = "REBATE_ACCRUAL"
    REINVEST_INCOME_PROVISIONAL = "REINVEST_INCOME_PROVISIONAL"
    REINVEST_INCOME_FINAL = "REINVEST_INCOME_FINAL"
    FAIL_FEE = "FAIL_FEE"
    BUY_IN_CHARGE = "BUY_IN_CHARGE"
    COLLATERAL_SEIZURE = "COLLATERAL_SEIZURE"
    INDEMNITY_CREDIT = "INDEMNITY_CREDIT"
    REVENUE_SPLIT_OWNER = "REVENUE_SPLIT_OWNER"
    REVENUE_SPLIT_AGENT = "REVENUE_SPLIT_AGENT"


class OverrideStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ReportType(str, Enum):
    MONTHLY_LOAN_ACTIVITY = "MONTHLY_LOAN_ACTIVITY"
    FAILS_AND_BUYINS = "FAILS_AND_BUYINS"
    COLLATERAL_SUMMARY = "COLLATERAL_SUMMARY"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    FILED = "FILED"


class PeriodCloseStatus(str, Enum):
    CLOSED = "CLOSED"


class UserRole(str, Enum):
    DESK_TRADER = "DeskTrader"
    BORROWER_REP = "BorrowerRep"
    OWNER_REP = "OwnerRep"
    RISK_OFFICER = "RiskOfficer"
    OPS_SETTLER = "OpsSettler"
    DESK_ADMIN = "DeskAdmin"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Most resources carry id + created_at + updated_at + version.
# RevenueLedgerEntry and PeriodClose are the documented exceptions: they carry
# only id and created_at (no updated_at, no version).
# ---------------------------------------------------------------------------


class Security(TypedDict, total=False):
    id: str
    symbol: str
    asset_class: str
    price_cents: int
    haircut_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BeneficialOwner(TypedDict, total=False):
    id: str
    display_name: str
    revenue_share_bps: int
    indemnification_opt_in: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Borrower(TypedDict, total=False):
    id: str
    display_name: str
    credit_limit_cents: int
    effective_limit_cents: int
    utilization_cents: int
    utilization_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LendablePosition(TypedDict, total=False):
    id: str
    owner_id: str
    security_id: str
    quantity_total: int
    min_fee_bps: int
    quantity_reserved: int
    quantity_on_loan: int
    quantity_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BorrowRequest(TypedDict, total=False):
    id: str
    borrower_id: str
    security_id: str
    quantity: int
    max_rate_bps: int
    collateral_type: str
    term_days: Optional[int]
    needed_by_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrow_request_id: Optional[str]
    position_id: str
    owner_id: str
    borrower_id: str
    security_id: str
    quantity: int
    outstanding_quantity: int
    collateral_type: str
    rate_bps: int
    term_days: Optional[int]
    original_price_cents: int
    market_value_cents: int
    required_collateral_cents: int
    posted_collateral_cents: int
    cash_uninvested_cents: int
    status: str
    margin_status: str
    created_at: str
    updated_at: str
    version: int


class CollateralPledge(TypedDict, total=False):
    id: str
    loan_id: str
    pledge_type: str
    amount_cents: Optional[int]
    pledge_security_id: Optional[str]
    quantity: Optional[int]
    marked_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarginCall(TypedDict, total=False):
    id: str
    loan_id: str
    amount_due_cents: int
    issued_date: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict, total=False):
    id: str
    loan_id: str
    owner_id: str
    quantity: int
    reason: str
    issue_date: str
    deadline_date: str
    delivered_quantity: int
    extended_once: bool
    fail_price_cents: Optional[int]
    fail_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReinvestmentTranche(TypedDict, total=False):
    id: str
    loan_id: str
    instrument_type: str
    principal_cents: int
    stated_yield_bps: int
    current_nav_cents: int
    realized_income_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueLedgerEntry(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    loan_id: Optional[str]
    owner_id: str
    entry_type: str
    amount_cents: int
    accrual_date: str
    period: str
    note: str
    created_at: str


class LimitOverride(TypedDict, total=False):
    id: str
    borrower_id: str
    new_limit_cents: int
    effective_from: str
    expires_at: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryReport(TypedDict, total=False):
    id: str
    period: str
    report_type: str
    total_on_loan_value_cents: Optional[int]
    total_fee_income_cents: Optional[int]
    total_rebate_expense_cents: Optional[int]
    fail_count: Optional[int]
    buy_in_count: Optional[int]
    finalized_by_user_id: Optional[str]
    filed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PeriodClose(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    period: str
    loans_finalized_count: int
    status: str
    created_at: str
