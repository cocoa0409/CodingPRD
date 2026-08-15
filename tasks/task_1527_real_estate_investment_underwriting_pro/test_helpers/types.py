"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANALYST = "Analyst"
    ASSET_MANAGER = "AssetManager"
    IC_MEMBER = "IC_Member"
    IC_CHAIR = "IC_Chair"
    ADMIN = "Admin"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDERWRITING = "UNDERWRITING"
    IC_REVIEW = "IC_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEAD = "DEAD"


class Strategy(str, Enum):
    CORE = "CORE"
    CORE_PLUS = "CORE_PLUS"
    VALUE_ADD = "VALUE_ADD"
    OPPORTUNISTIC = "OPPORTUNISTIC"


class PropertyType(str, Enum):
    MULTIFAMILY = "MULTIFAMILY"
    OFFICE = "OFFICE"
    RETAIL = "RETAIL"
    INDUSTRIAL = "INDUSTRIAL"
    MIXED_USE = "MIXED_USE"


class ExpenseCategory(str, Enum):
    TAXES = "TAXES"
    INSURANCE = "INSURANCE"
    UTILITIES = "UTILITIES"
    REPAIRS = "REPAIRS"
    MANAGEMENT = "MANAGEMENT"
    PAYROLL = "PAYROLL"
    MARKETING = "MARKETING"
    OTHER = "OTHER"


class ScenarioKind(str, Enum):
    BASE = "BASE"
    DOWNSIDE = "DOWNSIDE"
    UPSIDE = "UPSIDE"
    STRESS = "STRESS"


class ScenarioStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPUTED = "COMPUTED"
    SUPERSEDED = "SUPERSEDED"


class SizingConstraint(str, Enum):
    DSCR = "DSCR"
    LTV = "LTV"
    BOTH = "BOTH"


class Recommendation(str, Enum):
    PURSUE = "PURSUE"
    PASS = "PASS"
    RENEGOTIATE = "RENEGOTIATE"


class MemoStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_VOTE = "UNDER_VOTE"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class VoteValue(str, Enum):
    YES = "YES"
    NO = "NO"
    ABSTAIN = "ABSTAIN"


# --- Entities carrying the full common system fields (id, created_at,
# --- updated_at, version) per PRD §2.4 ---


class Deal(TypedDict, total=False):
    id: str
    deal_code: str
    deal_name: str
    strategy: str
    status: str
    target_purchase_price_cents: int
    analyst_id: str
    asset_manager_id: Optional[str]
    current_scenario_id: Optional[str]
    approved_at: Optional[str]
    rejected_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict, total=False):
    id: str
    deal_id: str
    address_line: str
    market: str
    property_type: str
    units: int
    rentable_sqft: int
    year_built: int
    occupancy_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class MarketAssumption(TypedDict, total=False):
    id: str
    deal_id: str
    label: str
    market_rent_growth_yr1_bps: int
    market_rent_growth_steady_bps: int
    expense_growth_bps: int
    exit_cap_rate_bps: int
    hold_period_years: int
    capex_per_unit_cents: int
    lease_up_months: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Scenario(TypedDict, total=False):
    id: str
    deal_id: str
    scenario_kind: str
    assumption_id: str
    occupancy_stress_pct: int
    status: str
    computed_noi_yr1_cents: Optional[int]
    computed_irr_bps: Optional[int]
    computed_equity_multiple_bp: Optional[int]
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DebtSizing(TypedDict, total=False):
    id: str
    scenario_id: str
    loan_amount_cents: int
    interest_rate_bps: int
    amortization_years: int
    io_months: int
    min_dscr_pct: int
    max_ltv_pct: int
    dscr_at_size_pct: int
    ltv_at_size_pct: int
    sizing_constraint: str
    created_at: str
    updated_at: str
    version: int


class Waterfall(TypedDict, total=False):
    id: str
    scenario_id: str
    pref_return_bps: int
    promote_tier1_bps: int
    tier1_hurdle_bps: int
    promote_tier2_bps: int
    lp_split_cents: int
    gp_split_cents: int
    gp_promote_cents: int
    created_at: str
    updated_at: str
    version: int


class ICMemo(TypedDict, total=False):
    id: str
    deal_id: str
    scenario_id: str
    recommendation: str
    thesis: str
    risks: str
    status: str
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only records (PRD §2.4): only id + created_at; NO updated_at,
# --- NO version ---


class RentRollPeriod(TypedDict, total=False):
    id: str
    property_id: str
    period_month: str
    occupied_units: int
    total_units: int
    gross_potential_rent_cents: int
    collected_rent_cents: int
    concessions_cents: int
    source_doc_ref: str
    created_at: str


class OperatingExpense(TypedDict, total=False):
    id: str
    property_id: str
    period_year: int
    category: str
    amount_cents: int
    is_recoverable: bool
    created_at: str


class ICVote(TypedDict, total=False):
    id: str
    memo_id: str
    voter_user_id: str
    vote: str
    comment: Optional[str]
    cast_at: str
    created_at: str
