"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLANT_MANAGER = "PlantManager"
    PRODUCTION_PLANNER = "ProductionPlanner"
    LINE_OPERATOR = "LineOperator"
    QA_TECHNICIAN = "QATechnician"
    QA_MANAGER = "QAManager"
    WAREHOUSE_LEAD = "WarehouseLead"
    COPACK_CUSTOMER = "CoPackCustomer"


class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RETIRED = "RETIRED"


class ProductStyle(str, Enum):
    ENTREE = "ENTREE"
    BOWL = "BOWL"
    SKILLET = "SKILLET"


class ComponentType(str, Enum):
    RAW_INGREDIENT = "RAW_INGREDIENT"
    SUB_ASSEMBLY = "SUB_ASSEMBLY"
    PACKAGING = "PACKAGING"


class UnitOfMeasure(str, Enum):
    KG = "KG"
    L = "L"
    EACH = "EACH"
    M = "M"


class BillingMethod(str, Enum):
    PER_CASE = "PER_CASE"
    PER_KG = "PER_KG"


class PackFormat(str, Enum):
    RETAIL = "RETAIL"
    FOODSERVICE = "FOODSERVICE"


class OrderStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BatchStatus(str, Enum):
    CREATED = "CREATED"
    KITTED = "KITTED"
    COOKED = "COOKED"
    FROZEN = "FROZEN"
    PACKED = "PACKED"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    REWORK = "REWORK"
    CANCELLED = "CANCELLED"


class CellStatus(str, Enum):
    IDLE = "IDLE"
    IN_USE = "IN_USE"


class CycleStatus(str, Enum):
    RESERVED = "RESERVED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class LineType(str, Enum):
    TRAY = "TRAY"
    POUCH = "POUCH"


class FilmType(str, Enum):
    TRAY_FILM = "TRAY_FILM"
    POUCH_FILM = "POUCH_FILM"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FilmLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"


class CheckType(str, Enum):
    METAL_DETECTOR = "METAL_DETECTOR"
    XRAY = "XRAY"


class CheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class Zone(str, Enum):
    FREEZER_A = "FREEZER_A"
    FREEZER_B = "FREEZER_B"
    DEEP_FREEZE = "DEEP_FREEZE"


class TemperatureClass(str, Enum):
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class ReleaseStatus(str, Enum):
    QA_PENDING = "QA_PENDING"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    QUARANTINED = "QUARANTINED"
    RECALLED = "RECALLED"
    DEPLETED = "DEPLETED"


class ComplaintType(str, Enum):
    FREEZER_BURN = "FREEZER_BURN"
    TEXTURE = "TEXTURE"
    FOREIGN_MATERIAL = "FOREIGN_MATERIAL"
    OFF_ODOR = "OFF_ODOR"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    RESOLVED_VALID = "RESOLVED_VALID"
    RESOLVED_INVALID = "RESOLVED_INVALID"


class WithdrawPurpose(str, Enum):
    SHIPMENT = "SHIPMENT"
    DESTRUCTION = "DESTRUCTION"


# --- Entity TypedDicts (PRD §2.5 common fields: id, created_at, updated_at, version) ---

class Recipe(TypedDict, total=False):
    id: str
    name: str
    product_style: str
    base_batch_yield_units: int
    portion_weight_g: float
    shelf_life_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecipeComponent(TypedDict, total=False):
    id: str
    recipe_id: str
    parent_component_id: Optional[str]
    component_name: str
    component_type: str
    quantity_per_base_batch: float
    unit_of_measure: str
    scale_exponent: float
    allergen_tag: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoPackCustomer(TypedDict, total=False):
    id: str
    name: str
    billing_method: str
    case_rate_cents: Optional[int]
    kg_rate_cents: Optional[int]
    requires_allergen_changeover: bool
    base_changeover_minutes: int
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict, total=False):
    id: str
    recipe_id: str
    copack_customer_id: Optional[str]
    pack_format: str
    units_planned: int
    due_at: Optional[str]
    units_packed_total: int
    releasable_cases: int
    billed_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionBatch(TypedDict, total=False):
    id: str
    order_id: str
    units_planned: int
    cooked_mass_kg: Optional[float]
    units_packed_total: int
    yield_pct: Optional[float]
    status: str
    hold_origin_state: Optional[str]
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BlastFreezerCell(TypedDict, total=False):
    id: str
    cell_code: str
    capacity_kg: int
    min_load_kg: int
    pull_down_kg_per_hour: int
    sanitation_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FreezingCycle(TypedDict, total=False):
    id: str
    batch_id: str
    cell_id: str
    load_kg: int
    entry_temp_c: float
    planned_start: str
    required_hours: int
    planned_end: str
    actual_end: Optional[str]
    final_core_temp_c: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagingLine(TypedDict, total=False):
    id: str
    line_code: str
    line_type: str
    rate_units_per_minute: int
    supported_film_type: str
    created_at: str
    updated_at: str
    version: int


class LineRun(TypedDict, total=False):
    id: str
    line_id: str
    batch_id: str
    film_lot_id: str
    planned_start: str
    units_planned: int
    duration_minutes: int
    planned_end: str
    reserved_film_m: int
    units_packed: Optional[int]
    film_meters_consumed: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class FilmSupplyLot(TypedDict, total=False):
    id: str
    film_type: str
    rolls_received: int
    meters_per_roll: int
    meters_received: int
    meters_reserved: int
    meters_consumed: int
    meters_available: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CCPCheck(TypedDict, total=False):
    # Append-only record (PRD §2.5): id + created_at only; no updated_at, no version.
    id: str
    batch_id: str
    check_type: str
    test_piece_detected: bool
    measured_size_mm: Optional[float]
    result: str
    performed_by_user_id: str
    performed_at: str
    created_at: str


class StorageSlot(TypedDict, total=False):
    id: str
    slot_code: str
    zone: str
    temperature_class: str
    capacity_cases: int
    occupied_cases: int
    created_at: str
    updated_at: str
    version: int


class FinishedGoodsLot(TypedDict, total=False):
    id: str
    batch_id: str
    slot_id: Optional[str]
    pack_format: str
    cases_produced: int
    net_weight_kg: float
    stored_cases: int
    cases_on_hand: int
    cases_shipped: int
    provisional_expiry_date: str
    final_expiry_date: str
    valid_complaint_count: int
    release_status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    lot_id: str
    complaint_type: str
    units_affected: int
    reported_by_user_id: str
    reported_at: str
    days_before_expiry: int
    status: str
    created_at: str
    updated_at: str
    version: int
