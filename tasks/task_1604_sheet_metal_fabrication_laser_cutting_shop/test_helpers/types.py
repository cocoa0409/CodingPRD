"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD §2.5 (common resource properties) and §3:
primary resources carry id + created_at + updated_at + version;
inspection reports and audit events are append-only and carry only
id + created_at (both updated_at and version are absent).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AlloyFamily(str, Enum):
    ALUMINUM = "ALUMINUM"
    CARBON_STEEL = "CARBON_STEEL"
    STAINLESS = "STAINLESS"


class SheetKind(str, Enum):
    FULL_SHEET = "FULL_SHEET"
    REMNANT = "REMNANT"


class SheetStockStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CONSUMED = "CONSUMED"
    SCRAPPED = "SCRAPPED"
    DROPPED_OFF = "DROPPED_OFF"


class Station(str, Enum):
    LASER = "LASER"
    BRAKE = "BRAKE"
    WELD = "WELD"
    POWDER = "POWDER"


class MachineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"


class VendorProcess(str, Enum):
    PLATING = "PLATING"
    ANODIZING = "ANODIZING"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ExpediteTier(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITE = "EXPEDITE"
    RUSH = "RUSH"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class Finish(str, Enum):
    NONE = "NONE"
    POWDER = "POWDER"
    PLATING = "PLATING"
    ANODIZING = "ANODIZING"


class QuoteLineStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    PRICED = "PRICED"
    SUPERSEDED = "SUPERSEDED"


class OrderStatus(str, Enum):
    NESTING = "NESTING"
    NESTED = "NESTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    AWAITING_OUTSIDE = "AWAITING_OUTSIDE"
    FINISHING = "FINISHING"
    INSPECTION = "INSPECTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    ON_HOLD = "ON_HOLD"


class HoldReason(str, Enum):
    CAPACITY = "CAPACITY"
    VENDOR_DELAY = "VENDOR_DELAY"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"


class RoutingStation(str, Enum):
    LASER = "LASER"
    BRAKE = "BRAKE"
    WELD = "WELD"
    POWDER = "POWDER"
    OUTSIDE_VENDOR = "OUTSIDE_VENDOR"


class RoutingStepStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ScrapCreditStatus(str, Enum):
    POSTED = "POSTED"
    APPLIED = "APPLIED"
    VOID = "VOID"


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    ESTIMATOR = "Estimator"
    CUSTOMER_REP = "CustomerRep"
    PRODUCTION_PLANNER = "ProductionPlanner"
    MACHINE_OPERATOR = "MachineOperator"
    QC_INSPECTOR = "QCInspector"
    INVENTORY_CLERK = "InventoryClerk"


# ---------------------------------------------------------------------------
# Entity shapes (primary resources: id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class Customer(TypedDict, total=False):
    id: str
    company_name: str
    email: str
    credit_limit_cents: int
    scrap_credit_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ThicknessTier(TypedDict):
    max_thickness_mm: float
    tier_index: int


class MaterialGrade(TypedDict, total=False):
    id: str
    code: str
    alloy_family: str
    density_g_per_cm3: float
    hardness_factor: float
    base_cut_rate_cents_per_sec: float
    material_cost_cents_per_cm2: float
    scrap_rate_cents_per_cm2: float
    thickness_tiers: List[ThicknessTier]
    weld_compatible: bool
    powder_compatible: bool
    created_at: str
    updated_at: str
    version: int


class SheetStock(TypedDict, total=False):
    id: str
    grade_id: str
    thickness_mm: float
    width_mm: int
    height_mm: int
    kind: str
    status: str
    source_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict, total=False):
    id: str
    name: str
    station: str
    shift_minutes_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutsideVendor(TypedDict, total=False):
    id: str
    name: str
    process: str
    lead_time_days: int
    base_cost_cents_per_part: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    customer_id: str
    expedite_tier: str
    status: str
    quoted_subtotal_cents: int
    quoted_expedite_cents: int
    quoted_total_cents: int
    submitted_at: Optional[str]
    expires_at: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class QuoteLine(TypedDict, total=False):
    id: str
    quote_id: str
    grade_id: str
    thickness_mm: float
    bbox_width_mm: int
    bbox_height_mm: int
    hole_count: int
    hole_diameter_mm: float
    corner_fillet_count: int
    bend_count: int
    weld_inches: float
    finish: str
    qty: int
    cut_seconds_est: float
    billed_cut_seconds: int
    thickness_tier_index: int
    bend_units: int
    finish_cost_cents: int
    material_cost_cents: int
    line_base_cents: int
    qty_discount_pct: float
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FabricationOrder(TypedDict, total=False):
    id: str
    quote_id: str
    customer_id: str
    expedite_tier: str
    status: str
    hold_reason: Optional[str]
    committed_subtotal_cents: int
    committed_total_cents: int
    total_plate_area_cm2: int
    scrap_credit_applied_cents: int
    payment_status: str
    paid_at: Optional[str]
    completed_at: Optional[str]
    due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NestSheet(TypedDict, total=False):
    id: str
    order_id: str
    sheet_stock_id: str
    sheet_index: int
    chargeable_area_cm2: float
    kerf_allowance_cm2: float
    plate_in_area_cm2: float
    yield_pct: float
    remnant_stock_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoutingStep(TypedDict, total=False):
    id: str
    order_id: str
    station: str
    seq: int
    machine_id: Optional[str]
    vendor_id: Optional[str]
    planned_minutes: int
    completing_operator_id: Optional[str]
    due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.5): only id + created_at; NO updated_at, NO version.
class InspectionReport(TypedDict, total=False):
    id: str
    order_id: str
    inspector_id: str
    flatness_deviation_mm: float
    measured_diagonal_mm: int
    dimensional_pass: bool
    result: str
    created_at: str


# Append-only (PRD §2.5): only id + created_at; NO updated_at, NO version.
class AuditEvent(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    event_type: str
    actor_role: str
    actor_id: str
    detail: Dict[str, Any]
    created_at: str


class ScrapCredit(TypedDict, total=False):
    id: str
    customer_id: str
    sheet_stock_id: str
    credited_area_cm2: float
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
