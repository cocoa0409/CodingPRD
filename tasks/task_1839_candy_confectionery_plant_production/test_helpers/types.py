"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PRODUCTION_PLANNER = "ProductionPlanner"
    PLANT_MANAGER = "PlantManager"
    LINE_OPERATOR = "LineOperator"
    SANITATION_LEAD = "SanitationLead"
    QUALITY_MANAGER = "QualityManager"


class ProductType(str, Enum):
    STANDARD = "STANDARD"
    SEASONAL = "SEASONAL"
    GIFT_SET = "GIFT_SET"


class Brand(str, Enum):
    OWN = "OWN"
    PRIVATE_LABEL = "PRIVATE_LABEL"


class Allergen(str, Enum):
    MILK = "MILK"
    SOY = "SOY"
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    EGG = "EGG"
    WHEAT = "WHEAT"
    SESAME = "SESAME"


class PackagingPOStatus(str, Enum):
    ORDERED = "ORDERED"
    RECEIVED = "RECEIVED"


class MoldStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INSTALLED = "INSTALLED"


class LineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHANGEOVER = "CHANGEOVER"


class ChangeoverType(str, Enum):
    SHAPE_ONLY = "SHAPE_ONLY"
    FULL = "FULL"
    ALLERGEN_WASH = "ALLERGEN_WASH"


class ChangeoverStatus(str, Enum):
    PENDING_SWAB = "PENDING_SWAB"
    PENDING_QA = "PENDING_QA"
    RELEASED = "RELEASED"


class WindowStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    CLOSED = "CLOSED"


class RunType(str, Enum):
    STANDARD = "STANDARD"
    GIFT_ASSEMBLY = "GIFT_ASSEMBLY"
    REWORK = "REWORK"


class RunStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"
    DEPLETED = "DEPLETED"
    SCRAPPED = "SCRAPPED"


class LotQualityStatus(str, Enum):
    OK = "OK"
    SUSPECT = "SUSPECT"


class DefectType(str, Enum):
    BLOOM = "BLOOM"
    TEMPER_DEVIATION = "TEMPER_DEVIATION"
    FOREIGN_MATERIAL = "FOREIGN_MATERIAL"
    OTHER = "OTHER"


class HoldStatus(str, Enum):
    OPEN = "OPEN"
    RELEASED = "RELEASED"
    SCRAPPED = "SCRAPPED"
    REWORK_PENDING = "REWORK_PENDING"
    CLOSED_REWORK = "CLOSED_REWORK"


class DispositionAction(str, Enum):
    RELEASE = "RELEASE"
    SCRAP = "SCRAP"
    REWORK = "REWORK"


# ---------------------------------------------------------------------------
# Entities carrying the standard system-managed fields
# (id + created_at + updated_at + version).
# ---------------------------------------------------------------------------

class Product(TypedDict):
    id: str
    sku_code: str
    name: str
    product_type: str
    brand: str
    customer_name: Optional[str]
    base_price_cents: int
    unit_weight_grams: float
    shelf_life_days: int
    packaging_component_id: str
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict):
    id: str
    product_id: str
    name: str
    shape_code: str
    cook_temp_min_c: float
    cook_temp_max_c: float
    temper_exit_min_c: float
    temper_exit_max_c: float
    allergens: List[str]
    standard_yield_pct: float
    created_at: str
    updated_at: str
    version: int


class PackagingComponent(TypedDict):
    id: str
    sku_code: str
    name: str
    units_per_component: int
    lead_time_days: int
    qty_on_hand: int
    qty_reserved: int
    qty_available: int
    created_at: str
    updated_at: str
    version: int


class PackagingPO(TypedDict):
    id: str
    component_id: str
    order_qty: int
    ordered_at: str
    due_at: str
    received_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Mold(TypedDict):
    id: str
    shape_code: str
    cavity_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict):
    id: str
    name: str
    current_mold_id: Optional[str]
    cleared_allergens: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Changeover(TypedDict):
    id: str
    line_id: str
    changeover_type: str
    to_mold_id: Optional[str]
    target_allergens: Optional[List[str]]
    swab_recorded_by: Optional[str]
    swab_passed: Optional[bool]
    qa_released_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarkdownTier(TypedDict):
    day_offset_min: int
    discount_pct: float


class SeasonalWindow(TypedDict):
    id: str
    season_code: str
    build_start: str
    build_end: str
    ship_start: str
    ship_end: str
    target_units: int
    markdown_tiers: List[MarkdownTier]
    confirmed_build_units: int
    projected_build_units: int
    coverage_pct: float
    shortfall: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    window_id: str
    product_id: str
    recipe_id: str
    line_id: str
    run_type: str
    planned_units: int
    scheduled_start: str
    scheduled_end: str
    source_lot_id: Optional[str]
    rework_qty: Optional[int]
    packaging_reserved_qty: int
    output_units: Optional[int]
    expected_output_units: Optional[int]
    created_lot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    product_id: str
    run_id: str
    mfg_date: str
    expiry_date: str
    qty_on_hand: int
    qty_reserved_rework: int
    qty_scrapped: int
    unit_price_cents: int
    quality_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityHold(TypedDict):
    id: str
    lot_id: str
    defect_type: str
    affected_units: int
    lot_qty_at_open: int
    defect_rate_pct: float
    opened_by: str
    disposition_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Gift-set bill-of-material rows are immutable after creation: they carry
# only id + created_at; updated_at and version are absent.
class GiftComponent(TypedDict):
    id: str
    gift_product_id: str
    component_product_id: str
    qty_per_set: int
    created_at: str
