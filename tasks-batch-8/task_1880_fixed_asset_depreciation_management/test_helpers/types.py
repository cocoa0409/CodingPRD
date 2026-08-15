"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ASSET_ACCOUNTANT = "AssetAccountant"
    CONTROLLER = "Controller"
    INVENTORY_CLERK = "InventoryClerk"
    TAX_ANALYST = "TaxAnalyst"


class ProjectStatus(str, Enum):
    OPEN = "OPEN"
    CAPITALIZED = "CAPITALIZED"
    CANCELLED = "CANCELLED"


class CostLineStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class CostType(str, Enum):
    MATERIAL = "MATERIAL"
    LABOR = "LABOR"
    VENDOR_INVOICE = "VENDOR_INVOICE"
    OTHER = "OTHER"


class AssetStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_SERVICE = "IN_SERVICE"
    FULLY_DEPRECIATED = "FULLY_DEPRECIATED"
    DISPOSED = "DISPOSED"


class AssetSource(str, Enum):
    PURCHASE = "PURCHASE"
    CIP_CAPITALIZATION = "CIP_CAPITALIZATION"
    COMPONENT_ADDITION = "COMPONENT_ADDITION"


class BookMethod(str, Enum):
    STRAIGHT_LINE = "STRAIGHT_LINE"
    DOUBLE_DECLINING = "DOUBLE_DECLINING"


class TaxMethod(str, Enum):
    MACRS_5YR = "MACRS_5YR"
    MACRS_7YR = "MACRS_7YR"
    TAX_STRAIGHT_LINE = "TAX_STRAIGHT_LINE"


class RunStatus(str, Enum):
    OPEN = "OPEN"
    POSTED = "POSTED"


class Ledger(str, Enum):
    BOOK = "BOOK"
    TAX = "TAX"


class EntrySource(str, Enum):
    RUN = "RUN"
    DISPOSAL_FINAL = "DISPOSAL_FINAL"


class DisposalType(str, Enum):
    SALE = "SALE"
    SCRAP = "SCRAP"
    TRANSFER = "TRANSFER"


class DisposalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    POSTED = "POSTED"
    REJECTED = "REJECTED"


class InventoryRunStatus(str, Enum):
    COUNTING = "COUNTING"
    RECONCILING = "RECONCILING"
    CLOSED = "CLOSED"


class ScopeType(str, Enum):
    ALL = "ALL"
    LOCATION = "LOCATION"
    COST_CENTER = "COST_CENTER"


class CountCondition(str, Enum):
    GOOD = "GOOD"
    DAMAGED = "DAMAGED"


class ReconciliationStatus(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    LOCATION_MISMATCH = "LOCATION_MISMATCH"
    MISSING = "MISSING"


class ImpairmentIndicator(str, Enum):
    DAMAGE = "DAMAGE"
    OBSOLESCENCE = "OBSOLESCENCE"
    MARKET_DECLINE = "MARKET_DECLINE"


class ReviewSource(str, Enum):
    MANUAL = "MANUAL"
    INVENTORY = "INVENTORY"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    WRITTEN_DOWN = "WRITTEN_DOWN"
    DISMISSED = "DISMISSED"


class ScheduleType(str, Enum):
    PROPERTY_TAX = "PROPERTY_TAX"
    INSURANCE = "INSURANCE"


class ScheduleStatus(str, Enum):
    IMPORTED = "IMPORTED"
    APPLIED = "APPLIED"


# --- Entity TypedDicts ---
# All entities below carry common fields: id, created_at, updated_at, version.
# DepreciationEntry is the PRD §2.4 exception: id + created_at only.


class AssetClass(TypedDict, total=False):
    id: str
    class_code: str
    name: str
    capitalization_threshold_cents: int
    default_useful_life_months: int
    book_method: str
    tax_method: str
    bonus_depreciation_allowed: bool
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict, total=False):
    id: str
    project_code: str
    name: str
    asset_class_id: str
    created_by_user_id: str
    total_accumulated_cents: int
    status: str
    capitalized_asset_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CIPCostLine(TypedDict, total=False):
    id: str
    project_id: str
    amount_cents: int
    cost_type: str
    incurred_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FixedAsset(TypedDict, total=False):
    id: str
    asset_tag: str
    description: str
    asset_class_id: str
    parent_asset_id: Optional[str]
    source: str
    acquisition_cost_cents: int
    salvage_value_cents: int
    useful_life_months: int
    book_method: str
    tax_method: str
    bonus_elected: bool
    cost_center: str
    location: str
    in_service_date: Optional[str]
    status: str
    accumulated_book_cents: int
    accumulated_tax_cents: int
    impairment_total_cents: int
    net_book_value_cents: int
    open_inventory_exception: bool
    created_at: str
    updated_at: str
    version: int


class DepreciationRun(TypedDict, total=False):
    id: str
    period: str
    status: str
    entries_created_count: int
    total_book_amount_cents: int
    total_tax_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class DepreciationEntry(TypedDict, total=False):
    # Append-only ledger line: id + created_at ONLY (no updated_at, no version).
    id: str
    created_at: str
    run_id: Optional[str]
    disposal_id: Optional[str]
    asset_id: str
    ledger: str
    period: str
    amount_cents: int
    source: str


class Disposal(TypedDict, total=False):
    id: str
    asset_id: str
    disposal_type: str
    proceeds_cents: int
    transfer_to_cost_center: Optional[str]
    effective_date: str
    requested_by_user_id: str
    approved_by_user_id: Optional[str]
    book_gain_loss_cents: Optional[int]
    tax_gain_loss_cents: Optional[int]
    auto_created: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryRun(TypedDict, total=False):
    id: str
    name: str
    scope_type: str
    scope_value: Optional[str]
    status: str
    expected_count: int
    matched_count: int
    missing_count: int
    mismatch_count: int
    created_at: str
    updated_at: str
    version: int


class InventoryCountLine(TypedDict, total=False):
    id: str
    run_id: str
    asset_id: str
    found: Optional[bool]
    counted_location: Optional[str]
    condition: str
    reconciliation_status: str
    created_at: str
    updated_at: str
    version: int


class ImpairmentReview(TypedDict, total=False):
    id: str
    asset_id: str
    indicator: str
    source: str
    created_by_user_id: str
    recoverable_value_cents: Optional[int]
    write_down_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ExternalSchedule(TypedDict, total=False):
    id: str
    asset_id: str
    schedule_type: str
    schedule_year: int
    assessed_value_cents: Optional[int]
    annual_premium_cents: Optional[int]
    property_tax_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
