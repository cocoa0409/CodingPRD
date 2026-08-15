"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3).

All entities share the common identity envelope of PRD §2.4: ``id``,
``created_at``, ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    TAX_DIRECTOR = "TaxDirector"
    BOARD_DIRECTOR = "BoardDirector"


class ReitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AssetClass(str, Enum):
    REAL_ESTATE = "REAL_ESTATE"
    QUALIFYING_SECURITY = "QUALIFYING_SECURITY"
    NON_QUALIFYING = "NON_QUALIFYING"


class AssetHoldingStatus(str, Enum):
    HELD = "HELD"
    SOLD = "SOLD"


class IncomeClass(str, Enum):
    RENTS = "RENTS"
    MORTGAGE_INTEREST = "MORTGAGE_INTEREST"
    NON_QUALIFYING = "NON_QUALIFYING"


class QuarterStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class TestReportStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    BREACHED = "BREACHED"


class HolderType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    ENTITY = "ENTITY"


class ShareholderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class SnapshotStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class RequirementStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    CLOSED = "CLOSED"


class DividendStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    DECLARED = "DECLARED"
    PAID = "PAID"
    VOID = "VOID"


class EpAdjustmentKind(str, Enum):
    TAXABLE_INCOME = "TAXABLE_INCOME"
    DISALLOWED_DEDUCTION = "DISALLOWED_DEDUCTION"
    FEDERAL_TAX = "FEDERAL_TAX"


class EpAdjustmentStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"


class AssetSaleStatus(str, Enum):
    DRAFT = "DRAFT"
    ANALYZED = "ANALYZED"
    CONFIRMED = "CONFIRMED"
    VOID = "VOID"


class DisclosureType(str, Enum):
    ASSET_TEST = "ASSET_TEST"
    INCOME_TEST = "INCOME_TEST"
    FIVE_FIFTY = "FIVE_FIFTY"
    DISTRIBUTION = "DISTRIBUTION"
    PROHIBITED_TRANSACTION = "PROHIBITED_TRANSACTION"


class DisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"


class Reit(TypedDict, total=False):
    id: str
    legal_name: str
    ticker: str
    charter_ownership_limit_pct: float
    taxable_year_start: str
    status: str
    current_ep_balance_cents: int
    dividend_distribution_deficit_cents: int
    five_fifty_blocked: bool
    created_at: str
    updated_at: str
    version: int


class AssetHolding(TypedDict, total=False):
    id: str
    reit_id: str
    asset_name: str
    asset_class: str
    held_by_trs: bool
    is_dealer_inventory: bool
    acquisition_date: str
    value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IncomeItem(TypedDict, total=False):
    id: str
    reit_id: str
    quarter_id: str
    income_class: str
    amount_cents: int
    source_is_trs: bool
    accrued_at: str
    created_at: str
    updated_at: str
    version: int


class Quarter(TypedDict, total=False):
    id: str
    reit_id: str
    label: str
    period_start: str
    period_end: str
    status: str
    gross_asset_total_cents: int
    gross_income_total_cents: int
    created_at: str
    updated_at: str
    version: int


class AssetTestReport(TypedDict, total=False):
    id: str
    reit_id: str
    quarter_id: str
    status: str
    qualifying_75_pct: float
    trs_concentration_pct: float
    test_75_passed: bool
    trs_test_passed: bool
    created_at: str
    updated_at: str
    version: int


class IncomeTestReport(TypedDict, total=False):
    id: str
    reit_id: str
    quarter_id: str
    status: str
    qualifying_75_pct: float
    qualifying_95_pct: float
    test_75_passed: bool
    test_95_passed: bool
    created_at: str
    updated_at: str
    version: int


class Shareholder(TypedDict, total=False):
    id: str
    reit_id: str
    display_name: str
    holder_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShareholderSnapshot(TypedDict, total=False):
    id: str
    reit_id: str
    snapshot_date: str
    total_shares_outstanding: int
    status: str
    top5_individual_pct: float
    five_fifty_passed: bool
    violator_shareholder_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class ShareholderPosition(TypedDict, total=False):
    id: str
    snapshot_id: str
    shareholder_id: str
    shares_held: int
    concentration_pct: float
    created_at: str
    updated_at: str
    version: int


class DistributionRequirement(TypedDict, total=False):
    id: str
    reit_id: str
    taxable_year: int
    status: str
    taxable_income_cents: int
    net_capital_gain_cents: int
    required_amount_cents: int
    distributed_amount_cents: int
    deficiency_cents: int
    created_at: str
    updated_at: str
    version: int


class DividendDeclaration(TypedDict, total=False):
    id: str
    reit_id: str
    taxable_year: int
    amount_cents: int
    declaration_date: str
    record_date: str
    payable_date: str
    status: str
    ordinary_cents: int
    capital_gain_cents: int
    return_of_capital_cents: int
    declared_by_officer_id: Optional[str]
    approved_by_director_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EpAdjustment(TypedDict, total=False):
    id: str
    reit_id: str
    quarter_id: str
    kind: str
    amount_cents: int
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AssetSale(TypedDict, total=False):
    id: str
    reit_id: str
    asset_holding_id: str
    sale_price_cents: int
    basis_cents: int
    sale_date: str
    status: str
    holding_period_months: int
    is_prohibited: bool
    prohibited_tax_cents: int
    created_at: str
    updated_at: str
    version: int


class ComplianceDisclosure(TypedDict, total=False):
    id: str
    reit_id: str
    disclosure_type: str
    reference_id: str
    title: str
    body: str
    status: str
    revision_count: int
    submitted_by_officer_id: Optional[str]
    decided_by_director_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
