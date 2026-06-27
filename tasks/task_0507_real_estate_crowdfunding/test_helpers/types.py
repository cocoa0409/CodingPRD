"""Domain types: entity TypedDicts, status enums, role enum for the Real Estate Crowdfunding API."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    FUND_MANAGER = "FundManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    OPERATOR = "Operator"
    INVESTOR = "Investor"
    ANONYMOUS = "Anonymous"


# --- Status / enum types (PRD §3) ---
class FundStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_TO_NEW = "CLOSED_TO_NEW"
    WINDING_DOWN = "WINDING_DOWN"


class VehicleType(str, Enum):
    REIT = "REIT"
    PARTNERSHIP = "PARTNERSHIP"


class ShareClassStatus(str, Enum):
    OFFERING = "OFFERING"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ProjectStatus(str, Enum):
    ACQUIRED = "ACQUIRED"
    STABILIZED = "STABILIZED"
    DISPOSED = "DISPOSED"


class AccreditedStatus(str, Enum):
    NON_ACCREDITED = "NON_ACCREDITED"
    ACCREDITED = "ACCREDITED"


class SuitabilityStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SubscriptionStatus(str, Enum):
    PENDING_ACH = "PENDING_ACH"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"
    CANCELLED = "CANCELLED"


class DistributionStatus(str, Enum):
    DECLARED = "DECLARED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class AllocationMode(str, Enum):
    CASH = "CASH"
    DRIP = "DRIP"


class RedemptionStatus(str, Enum):
    QUEUED = "QUEUED"
    DEFERRED = "DEFERRED"
    FULFILLED = "FULFILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TaxDocType(str, Enum):
    FORM_1099_DIV = "FORM_1099_DIV"
    FORM_K1 = "FORM_K1"


# --- Entity TypedDicts ---
# Entities with full common fields carry id + created_at + updated_at + version.

class Fund(TypedDict):
    id: str
    name: str
    vehicle_type: str
    status: str
    gross_asset_value_cents: int
    total_liabilities_cents: int
    shares_outstanding: float
    nav_per_share_cents: int
    total_capital_cents: int
    current_valuation_seq: int
    created_at: str
    updated_at: str
    version: int


class ShareClass(TypedDict):
    id: str
    fund_id: str
    class_code: str
    min_investment_cents: int
    mgmt_fee_bps: int
    accredited_only: bool
    drip_eligible: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    fund_id: str
    name: str
    acquisition_cost_cents: int
    appraised_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict):
    id: str
    email: str
    full_name: str
    accredited_status: str
    annual_income_cents: int
    net_worth_cents: int
    suitability_status: str
    reviewed_by_user_id: Optional[str]
    ytd_invested_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    investor_id: str
    share_class_id: str
    funded_amount_cents: int
    drip_elected: bool
    status: str
    provisional_nav_cents: int
    settled_nav_cents: Optional[int]
    shares_allocated: Optional[float]
    ach_fee_cents: int
    total_charged_cents: Optional[int]
    tax_year: Optional[int]
    holding_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Holding(TypedDict):
    id: str
    investor_id: str
    share_class_id: str
    shares_owned: float
    cost_basis_cents: int
    first_acquired_seq: Optional[int]
    drip_elected: bool
    created_at: str
    updated_at: str
    version: int


class Distribution(TypedDict):
    id: str
    fund_id: str
    period_label: str
    dividend_per_share_cents: float
    status: str
    total_paid_cents: int
    drip_shares_minted: float
    created_at: str
    updated_at: str
    version: int


class RedemptionRequest(TypedDict):
    id: str
    holding_id: str
    shares_requested: float
    status: str
    queue_seq: int
    gross_value_cents: Optional[int]
    penalty_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    penalty_tier_rate_bps: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only entities (common_fields: false) carry ONLY id + created_at.

class Valuation(TypedDict):
    id: str
    fund_id: str
    seq: int
    period_label: str
    gross_asset_value_cents: int
    total_liabilities_cents: int
    resulting_nav_per_share_cents: int
    created_at: str


class DistributionAllocation(TypedDict):
    id: str
    distribution_id: str
    holding_id: str
    gross_dividend_cents: int
    mode: str
    drip_shares: float
    created_at: str


class TaxDocument(TypedDict):
    id: str
    investor_id: str
    fund_id: str
    tax_year: int
    doc_type: str
    ordinary_dividends_cents: int
    reinvested_dividends_cents: int
    created_at: str
