"""Domain types: entity TypedDicts, status enums, role enum for the
Utility Capital Costing API (PRD §2-§4)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Enumerations (PRD §3)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    PROJECT_ENGINEER = "ProjectEngineer"
    WORK_ORDER_SUPERVISOR = "WorkOrderSupervisor"
    CONTROLLER = "Controller"
    FIELD_CLERK = "FieldClerk"
    RATE_ANALYST = "RateAnalyst"
    AUDITOR = "Auditor"


class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderType(str, Enum):
    CAPITAL = "CAPITAL"
    EXPENSE = "EXPENSE"


class AfudcMethod(str, Enum):
    HALF_MONTH = "HALF_MONTH"
    FULL_MONTH = "FULL_MONTH"


class CiacMethod(str, Enum):
    NET_OF_CIAC = "NET_OF_CIAC"
    GROSS_WITH_CONTRA = "GROSS_WITH_CONTRA"


class AssetClass(str, Enum):
    POLE = "POLE"
    TRANSFORMER = "TRANSFORMER"
    CONDUCTOR = "CONDUCTOR"
    METER = "METER"
    REGULATOR = "REGULATOR"


class CostType(str, Enum):
    LABOR = "LABOR"
    EQUIPMENT = "EQUIPMENT"
    MATERIAL = "MATERIAL"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"


class AccountingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class WorkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    AUTHORIZED = "AUTHORIZED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class VariancePosture(str, Enum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    RE_ESTIMATE_REQUIRED = "RE_ESTIMATE_REQUIRED"


class WriteoffDisposition(str, Enum):
    EXPENSE = "EXPENSE"
    REGULATORY_DEFERRAL = "REGULATORY_DEFERRAL"


class EstimateStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RoutingTier(str, Enum):
    SUPERVISOR = "SUPERVISOR"
    CONTROLLER = "CONTROLLER"


class ChargeKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    REVERSAL = "REVERSAL"


class ChargeStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class CiacStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class FixedAssetUnitStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    RETIRED = "RETIRED"


class RegulatoryAssetStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    AMORTIZING = "AMORTIZING"
    REJECTED = "REJECTED"
    FULLY_AMORTIZED = "FULLY_AMORTIZED"


class AfudcEntryStatus(str, Enum):
    ACCRUED = "ACCRUED"
    REVERSED = "REVERSED"


class EntryStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 common fields; §2.4 notes the three ledger-entry
# resources carry only id + created_at — no updated_at, no version)
# ---------------------------------------------------------------------------

class CapitalProgram(TypedDict, total=False):
    id: str
    code: str
    fiscal_year: int
    authorized_amount_cents: int
    afudc_debt_rate_pct: float
    afudc_equity_rate_pct: float
    afudc_debt_weight_pct: float
    afudc_method: str
    ciac_method: str
    status: str
    committed_amount_cents: int
    capitalized_actual_cents: int
    expense_writeoff_cents: int
    ciac_contra_balance_cents: int
    available_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class UnitCatalogEntry(TypedDict, total=False):
    id: str
    asset_class: str
    standard_cost_cents: int
    annual_depreciation_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class OverheadSchedule(TypedDict, total=False):
    id: str
    cost_type: str
    order_type: str
    rate_pct: float
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountingPeriod(TypedDict, total=False):
    id: str
    fiscal_year: int
    period_no: int
    start_date: str
    end_date: str
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    program_id: str
    order_type: str
    title: str
    status: str
    variance_posture: str
    estimate_seq: int
    approved_estimate_cents: Optional[int]
    actual_direct_cents: int
    afudc_total_cents: int
    cwip_cents: int
    in_service_date: Optional[str]
    in_service_period_id: Optional[str]
    gross_cwip_cents: Optional[int]
    ciac_applied_cents: int
    capitalizable_total_cents: Optional[int]
    cancel_writeoff_disposition: Optional[str]
    created_by_user_id: str
    authorized_by_user_id: Optional[str]
    completed_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict, total=False):
    id: str
    work_order_id: str
    estimate_seq: int
    estimated_cost_cents: int
    notes: Optional[str]
    status: str
    supersedes_estimate_id: Optional[str]
    submitted_by_user_id: str
    decided_by_user_id: Optional[str]
    routing_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CostCharge(TypedDict, total=False):
    id: str
    work_order_id: str
    cost_type: str
    base_amount_cents: int
    charge_date: str
    accounting_period_id: str
    kind: str
    reverses_charge_id: Optional[str]
    overhead_rate_pct: float
    overhead_amount_cents: int
    total_cents: int
    status: str
    posted_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class CiacAgreement(TypedDict, total=False):
    id: str
    work_order_id: str
    pledged_cents: int
    pledge_expiry_at: str
    status: str
    received_cents: Optional[int]
    applied_cents: Optional[int]
    forfeited_cents: Optional[int]
    refunded_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FixedAssetUnit(TypedDict, total=False):
    id: str
    work_order_id: str
    unit_catalog_id: str
    quantity: int
    line_no: int
    allocated_cost_cents: int
    in_service_period_id: str
    retirement_period_id: Optional[str]
    accumulated_depreciation_cents: int
    retirement_nbv_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RegulatoryAsset(TypedDict, total=False):
    id: str
    description: str
    source_work_order_id: Optional[str]
    original_cents: int
    amortization_months: int
    remaining_cents: int
    status: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger entries (PRD §2.4): only id + created_at; NO updated_at,
# NO version — an entry is never mutated in place.
class AfudcEntry(TypedDict, total=False):
    id: str
    work_order_id: str
    accounting_period_id: str
    method: str
    base_cents: int
    rate_pct_applied: float
    amount_cents: int
    status: str
    created_at: str


class DepreciationEntry(TypedDict, total=False):
    id: str
    fixed_asset_unit_id: str
    accounting_period_id: str
    amount_cents: int
    ciac_contra_credit_cents: int
    status: str
    created_at: str


class AmortizationEntry(TypedDict, total=False):
    id: str
    regulatory_asset_id: str
    accounting_period_id: str
    amount_cents: int
    status: str
    created_at: str
