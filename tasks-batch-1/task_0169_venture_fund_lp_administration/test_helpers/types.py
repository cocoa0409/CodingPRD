"""Domain types: entity TypedDicts, status enums, role enum.

All monetary amounts are integer cents; all rates are integer basis points.
Every persisted resource carries id, created_at, updated_at, and version.
"""
from enum import Enum
from typing import TypedDict, List


# --- Roles -----------------------------------------------------------------

class UserRole(str, Enum):
    FUND_MANAGER = "FundManager"
    FUND_ADMINISTRATOR = "FundAdministrator"
    LIMITED_PARTNER_USER = "LimitedPartnerUser"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums ----------------------------------------------------------

class FundStatus(str, Enum):
    FORMING = "FORMING"
    INVESTING = "INVESTING"
    HARVESTING = "HARVESTING"
    WOUND_DOWN = "WOUND_DOWN"


class CommitmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    CLOSED = "CLOSED"


class CapitalCallStatus(str, Enum):
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    PARTIALLY_DEFAULTED = "PARTIALLY_DEFAULTED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class CapitalCallAllocationStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    DEFAULTED = "DEFAULTED"
    WAIVED = "WAIVED"


class PortfolioCompanyStatus(str, Enum):
    PROSPECT = "PROSPECT"
    HELD = "HELD"
    EXITED = "EXITED"
    WRITTEN_OFF = "WRITTEN_OFF"


class InvestmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REALIZED = "REALIZED"
    IMPAIRED = "IMPAIRED"


class ValuationMarkStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class ManagementFeeAccrualStatus(str, Enum):
    ACCRUED = "ACCRUED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class DistributionEventStatus(str, Enum):
    DECLARED = "DECLARED"
    PAID = "PAID"
    RECALLED = "RECALLED"
    REVERSED = "REVERSED"


class SideLetterStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class LpType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    INSTITUTION = "INSTITUTION"
    FUND_OF_FUNDS = "FUND_OF_FUNDS"
    SOVEREIGN = "SOVEREIGN"


class CallPurpose(str, Enum):
    INVESTMENT = "INVESTMENT"
    MANAGEMENT_FEE = "MANAGEMENT_FEE"
    EXPENSE = "EXPENSE"


class DistributionType(str, Enum):
    RETURN_OF_CAPITAL = "RETURN_OF_CAPITAL"
    CAPITAL_GAIN = "CAPITAL_GAIN"
    INCOME = "INCOME"


class Methodology(str, Enum):
    LAST_ROUND = "LAST_ROUND"
    DCF = "DCF"
    COMPARABLES = "COMPARABLES"
    WRITE_OFF = "WRITE_OFF"


# --- Entity TypedDicts (all entities are mutable ledger objects) -----------

class Fund(TypedDict):
    id: str
    name: str
    vintage_year: int
    target_size_cents: int
    mgmt_fee_rate_bps: int
    carry_rate_bps: int
    pref_rate_bps: int
    gp_catchup_rate_bps: int
    recycling_cap_pct_bps: int
    fee_offset_pct_bps: int
    status: str
    total_committed_cents: int
    total_called_cents: int
    total_distributed_cents: int
    recycled_to_date_cents: int
    created_at: str
    updated_at: str
    version: int


class LimitedPartner(TypedDict):
    id: str
    legal_name: str
    lp_type: str
    tax_id_last4: str
    is_tax_exempt: bool
    default_strike_count: int
    created_at: str
    updated_at: str
    version: int


class Commitment(TypedDict):
    id: str
    fund_id: str
    lp_id: str
    committed_cents: int
    status: str
    drawn_cents: int
    distributed_cents: int
    unfunded_cents: int
    created_at: str
    updated_at: str
    version: int


class CapitalCall(TypedDict):
    id: str
    fund_id: str
    call_number: int
    purpose: str
    called_amount_cents: int
    due_date: str
    status: str
    funded_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class CapitalCallAllocation(TypedDict):
    id: str
    capital_call_id: str
    commitment_id: str
    allocated_amount_cents: int
    paid_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PortfolioCompany(TypedDict):
    id: str
    name: str
    sector: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Investment(TypedDict):
    id: str
    fund_id: str
    portfolio_company_id: str
    cost_basis_cents: int
    ownership_pct_bps: int
    status: str
    current_mark_cents: int
    realized_proceeds_cents: int
    created_at: str
    updated_at: str
    version: int


class ValuationMark(TypedDict):
    id: str
    investment_id: str
    as_of_date: str
    fair_value_cents: int
    methodology: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ManagementFeeAccrual(TypedDict):
    id: str
    fund_id: str
    period_start: str
    period_end: str
    gross_fee_cents: int
    offset_applied_cents: int
    net_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionEvent(TypedDict):
    id: str
    fund_id: str
    source_investment_id: str
    gross_amount_cents: int
    distribution_type: str
    recyclable: bool
    lp_share_cents: int
    gp_carry_cents: int
    recycled_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DistributionAllocation(TypedDict):
    id: str
    distribution_event_id: str
    commitment_id: str
    amount_cents: int
    clawback_flag: bool
    created_at: str
    updated_at: str
    version: int


class SideLetter(TypedDict):
    id: str
    fund_id: str
    lp_id: str
    mfn_rank: int
    fee_discount_bps: int
    excused_purposes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int
