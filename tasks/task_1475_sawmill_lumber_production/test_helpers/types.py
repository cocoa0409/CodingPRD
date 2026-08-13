"""Domain types: entity TypedDicts, status enums, role enum for the sawmill API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SCALER = "Scaler"
    SAWYER = "Sawyer"
    KILN_OPERATOR = "KilnOperator"
    GRADER = "Grader"
    SALES_REP = "SalesRep"
    MILL_MANAGER = "MillManager"


class Species(str, Enum):
    DOUGLAS_FIR = "DOUGLAS_FIR"
    PONDEROSA_PINE = "PONDEROSA_PINE"
    HEMLOCK_FIR = "HEMLOCK_FIR"
    CEDAR = "CEDAR"


class LogGrade(str, Enum):
    PEELER = "PEELER"
    SAWLOG_1 = "SAWLOG_1"
    SAWLOG_2 = "SAWLOG_2"
    UTILITY = "UTILITY"


class SawLine(str, Enum):
    LINE_A = "LINE_A"
    LINE_B = "LINE_B"


class SawingPattern(str, Enum):
    DIMENSION_2X4 = "DIMENSION_2X4"
    STUD_MIX = "STUD_MIX"
    TIMBER_4X4 = "TIMBER_4X4"


class Chamber(str, Enum):
    KILN_1 = "KILN_1"
    KILN_2 = "KILN_2"
    KILN_3 = "KILN_3"


class Dimension(str, Enum):
    DIM_2X4 = "2X4"
    DIM_2X6 = "2X6"
    DIM_4X4 = "4X4"


class StampedGrade(str, Enum):
    SELECT_STRUCT = "SELECT_STRUCT"
    NO_2 = "NO_2"
    NO_3 = "NO_3"
    ECONOMY = "ECONOMY"


class ByproductProduct(str, Enum):
    CHIP = "CHIP"
    SAWDUST = "SAWDUST"
    BARK = "BARK"


class PricingMode(str, Enum):
    CONTRACT = "CONTRACT"
    SPOT = "SPOT"


class InspectionAction(str, Enum):
    STAMP = "STAMP"
    RESTAMP = "RESTAMP"


class LogLoadStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCALED = "SCALED"
    DISPUTED = "DISPUTED"
    DECKED = "DECKED"
    CONSUMED = "CONSUMED"


class SawingRunStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"


class KilnChargeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class LumberPackageStatus(str, Enum):
    GREEN = "GREEN"
    IN_KILN = "IN_KILN"
    DRY = "DRY"
    STAMPED = "STAMPED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"


class SalesContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class SalesOrderStatus(str, Enum):
    PLACED = "PLACED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts ---
# LogLoad / SawingRun / KilnCharge / LumberPackage / SalesContract / SalesOrder
# carry id + created_at + updated_at + version (full mutation-tracking record).
# GradeInspection / PriceList / ByproductSale are append-only records that
# carry id + created_at only (PRD Section 2.4 lighter resource kinds).


class LogLoad(TypedDict, total=False):
    id: str
    supplier_name: str
    species: str
    log_grade: str
    scaled_mbf: Optional[float]
    price_per_mbf_cents: Optional[int]
    purchase_cost_cents: Optional[int]
    status: str
    decked_at: Optional[str]
    days_in_deck: int
    degrade_pct: float
    effective_mbf: Optional[float]
    sawing_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SawingRun(TypedDict, total=False):
    id: str
    saw_line: str
    scheduled_date: str
    sawing_pattern: str
    log_load_ids: List[str]
    status: str
    input_mbf: Optional[float]
    output_green_mbf: Optional[float]
    recovery_pct_provisional: Optional[float]
    recovery_pct_certified: Optional[float]
    completed_at: Optional[str]
    chip_tons: Optional[float]
    sawdust_tons: Optional[float]
    bark_tons: Optional[float]
    created_at: str
    updated_at: str
    version: int


class KilnCharge(TypedDict, total=False):
    id: str
    chamber: str
    species: str
    package_ids: List[str]
    scheduled_start: str
    scheduled_end: str
    target_moisture_pct: float
    status: str
    actual_start: Optional[str]
    actual_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LumberPackage(TypedDict, total=False):
    id: str
    sawing_run_id: str
    species: str
    dimension: str
    length_ft: int
    pieces: int
    green_mbf: float
    estimated_dry_mbf: float
    actual_dry_mbf: Optional[float]
    dry_mbf: float
    kiln_charge_id: Optional[str]
    exit_moisture_pct: Optional[float]
    stamped_grade: Optional[str]
    status: str
    stamped_at: Optional[str]
    sales_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GradeInspection(TypedDict, total=False):
    id: str
    package_id: str
    inspector_grade: str
    action: str
    note: Optional[str]
    created_at: str


class SalesContract(TypedDict, total=False):
    id: str
    customer_name: str
    species: str
    grade: str
    committed_mbf: float
    contract_price_per_mbf_cents: int
    start_date: str
    end_date: str
    status: str
    reserved_mbf: float
    shipped_mbf: float
    remaining_mbf: float
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_name: str
    contract_id: Optional[str]
    species: str
    grade: str
    length_spec: object  # "RL" or one of 8, 10, 12, 16
    volume_mbf: float
    pricing_mode: str
    unit_price_cents: int
    allocated_mbf: float
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceList(TypedDict, total=False):
    id: str
    species: str
    grade: str
    base_price_per_mbf_cents: int
    effective_from: str
    created_at: str


class ByproductSale(TypedDict, total=False):
    id: str
    product: str
    volume_tons: float
    price_per_ton_cents: int
    buyer_name: str
    total_cents: int
    created_at: str
