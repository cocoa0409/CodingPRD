"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALES_ENGINEER = "SalesEngineer"
    DESIGN_ENGINEER = "DesignEngineer"
    QUALITY_ENGINEER = "QualityEngineer"
    PLANT_MANAGER = "PlantManager"
    CUSTOMER = "Customer"


class AccountTier(str, Enum):
    STANDARD = "STANDARD"
    CONTRACT = "CONTRACT"


class FoamFamily(str, Enum):
    PE = "PE"
    EPE = "EPE"
    PU = "PU"
    XLPE = "XLPE"


class PackageSpecStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_VALIDATION = "IN_VALIDATION"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"


class CutMethod(str, Enum):
    DIE_CUT = "DIE_CUT"
    CNC_ROUTE = "CNC_ROUTE"


class CutProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    NESTED = "NESTED"
    LOCKED = "LOCKED"
    OBSOLETE = "OBSOLETE"


class ToolingStatus(str, Enum):
    ORDERED = "ORDERED"
    IN_SERVICE = "IN_SERVICE"
    RETIRED = "RETIRED"


class DropOrientation(str, Enum):
    FLAT = "FLAT"
    EDGE = "EDGE"
    CORNER = "CORNER"


class DropTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DropTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECORDED = "RECORDED"


class FabStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QualityHold(str, Enum):
    NONE = "NONE"
    ON_HOLD = "ON_HOLD"


class OrderKind(str, Enum):
    CUSTOMER = "CUSTOMER"
    REPLENISHMENT = "REPLENISHMENT"


class PricingMode(str, Enum):
    LOCKED = "LOCKED"
    CURRENT = "CURRENT"


class InventoryProgramStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ReleaseOrderStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class ScrapBatchStatus(str, Enum):
    COLLECTED = "COLLECTED"
    PROCESSED = "PROCESSED"
    CREDITED = "CREDITED"


# All entities carry the common system-managed properties of PRD §2.4:
# id (UUID), created_at, updated_at, version.


class Customer(TypedDict):
    id: str
    name: str
    account_tier: str
    branding_required: bool
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Material(TypedDict):
    id: str
    foam_family: str
    density_pcf: float
    ild_lb_25: int
    sheet_length_in: float
    sheet_width_in: float
    sheet_thickness_in: float
    cost_per_board_ft_cents: int
    recyclable: bool
    scrap_credit_per_lb_cents: int
    created_at: str
    updated_at: str
    version: int


class PackageSpec(TypedDict):
    id: str
    customer_id: str
    material_id: str
    part_name: str
    part_length_in: float
    part_width_in: float
    product_weight_lb: float
    required_drop_height_in: int
    max_fragility_g: int
    required_ild_lb: int
    revision_no: int
    status: str
    signed_off_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CutProgram(TypedDict):
    id: str
    package_spec_id: str
    method: str
    machine_seconds_per_part: Optional[int]
    supersedes_cut_program_id: Optional[str]
    parts_per_sheet: Optional[int]
    sheet_utilization_pct: Optional[float]
    offcut_sqft_per_sheet: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Tooling(TypedDict):
    id: str
    cut_program_id: str
    die_cost_cents: int
    amortization_qty: int
    lead_time_days: int
    amortized_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DropTest(TypedDict):
    id: str
    package_spec_id: str
    scheduled_start: str
    scheduled_end: str
    drop_height_in: int
    orientation: str
    pass_limit_g: int
    spec_revision_no: int
    measured_peak_g: Optional[int]
    result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict):
    id: str
    package_spec_id: str
    cut_program_id: str
    inventory_program_id: Optional[str]
    order_kind: str
    qty: int
    provisional_unit_price_cents: int
    provisional_total_cents: int
    final_unit_price_cents: Optional[int]
    final_total_cents: Optional[int]
    tooling_amort_cents: Optional[int]
    machine_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    fab_status: str
    quality_hold: str
    created_at: str
    updated_at: str
    version: int


class InventoryProgram(TypedDict):
    id: str
    customer_id: str
    package_spec_id: str
    pricing_mode: str
    max_stock_qty: int
    reorder_point_qty: int
    min_release_qty: int
    locked_material_cost_bf_cents: Optional[int]
    status: str
    produced_qty: int
    on_hand_qty: int
    reserved_qty: int
    shipped_qty: int
    created_at: str
    updated_at: str
    version: int


class ReleaseOrder(TypedDict):
    id: str
    inventory_program_id: str
    qty: int
    requested_ship_date: str
    unit_price_cents: Optional[int]
    total_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScrapBatch(TypedDict):
    id: str
    production_order_id: str
    gross_weight_lb: float
    contamination_pct: float
    net_recyclable_lb: float
    credit_cents: Optional[int]
    credited_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
