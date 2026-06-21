"""Domain types for the Donor-Advised Fund API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SPONSOR_ADMIN = "SponsorAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CONTRIBUTION_ADMIN = "ContributionAdmin"
    DONOR_ADVISOR = "DonorAdvisor"
    GRANT_OFFICER = "GrantOfficer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class InvestmentPoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class NavPeriodStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class CharityStatus(str, Enum):
    PENDING_VETTING = "PENDING_VETTING"
    VETTED = "VETTED"
    WATCHLISTED = "WATCHLISTED"
    REVOKED = "REVOKED"


class DonorAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    WIND_DOWN = "WIND_DOWN"
    CLOSED = "CLOSED"


class ContributionStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"


class AssetType(str, Enum):
    CASH = "CASH"
    SECURITIES = "SECURITIES"
    CRYPTO = "CRYPTO"


class PoolAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIQUIDATED = "LIQUIDATED"


class GrantStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class GrantRecurrence(str, Enum):
    ONE_TIME = "ONE_TIME"
    RECURRING = "RECURRING"


class SuccessionPlanType(str, Enum):
    SUCCESSOR_ADVISOR = "SUCCESSOR_ADVISOR"
    LEGACY_GRANTS = "LEGACY_GRANTS"


class SuccessionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"


class RebalanceOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class LedgerEntryType(str, Enum):
    CONTRIBUTION_SETTLED = "CONTRIBUTION_SETTLED"
    POOL_BUY = "POOL_BUY"
    POOL_REDEEM = "POOL_REDEEM"
    GRANT_PAID = "GRANT_PAID"
    ADMIN_FEE = "ADMIN_FEE"
    LEGACY_DISBURSEMENT = "LEGACY_DISBURSEMENT"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Resources with the full id/created_at/updated_at/version set carry all four.
# SubstantiationReceipt and LedgerEntry are append-only audit records and carry
# ONLY id + created_at (no updated_at, no version).
# ---------------------------------------------------------------------------
class Sponsor(TypedDict):
    id: str
    name: str
    ein: str
    minimum_grant_cents: int
    inactivity_quarters: int
    admin_fee_bps_default: int
    current_quarter_index: int
    created_at: str
    updated_at: str
    version: int


class InvestmentPool(TypedDict):
    id: str
    sponsor_id: str
    name: str
    risk_tier: str
    nav_per_unit_cents: int
    fee_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NavPeriod(TypedDict):
    id: str
    investment_pool_id: str
    from_quarter: int
    to_quarter: int
    nav_per_unit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Charity(TypedDict):
    id: str
    sponsor_id: str
    legal_name: str
    ein: str
    ntee_code: str
    is_private_foundation: bool
    status: str
    vetting_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonorAccount(TypedDict):
    id: str
    sponsor_id: str
    account_name: str
    primary_advisor_user_id: str
    cash_balance_cents: int
    invested_value_cents: int
    committed_grants_cents: int
    admin_fee_accrued_cents: int
    grantable_balance_cents: int
    last_grant_paid_quarter: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    donor_account_id: str
    asset_type: str
    cash_amount_cents: Optional[int]
    ticker: Optional[str]
    quantity_milli: Optional[int]
    high_price_cents: Optional[int]
    low_price_cents: Optional[int]
    closing_price_cents: Optional[int]
    spot_price_cents: Optional[int]
    thinly_traded: bool
    fair_market_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit record (id + created_at only)
class SubstantiationReceipt(TypedDict):
    id: str
    contribution_id: str
    donor_account_id: str
    receipt_number: str
    deductible_value_cents: int
    asset_description: str
    issued_quarter_index: int
    created_at: str


class PoolAllocation(TypedDict):
    id: str
    donor_account_id: str
    investment_pool_id: str
    units_micro: int
    target_pct_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrantRecommendation(TypedDict):
    id: str
    donor_account_id: str
    charity_id: str
    amount_cents: int
    is_anonymous: bool
    purpose: Optional[str]
    recurrence: str
    effective_from_quarter: Optional[int]
    effective_to_quarter: Optional[int]
    recommended_by_user_id: str
    approved_by_user_id: Optional[str]
    paid_quarter_index: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SuccessionPlan(TypedDict):
    id: str
    donor_account_id: str
    plan_type: str
    beneficiaries: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class RebalanceOrder(TypedDict):
    id: str
    donor_account_id: str
    source_pool_id: Optional[str]
    target_pool_id: Optional[str]
    amount_cents: int
    source_units_redeemed_micro: int
    target_units_bought_micro: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit record (id + created_at only)
class LedgerEntry(TypedDict):
    id: str
    donor_account_id: str
    entry_type: str
    signed_amount_cents: int
    ref_entity: str
    ref_id: str
    quarter_index: int
    created_at: str
