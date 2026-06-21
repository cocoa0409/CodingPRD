"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exactly as named in the PRD. Append-only records
(LotConsumption, CheckweighSample, CmrLedgerEntry, SanitationEvent) carry
only id + created_at; they have no updated_at and no version.
"""
from enum import Enum
from typing import TypedDict, List


# --- Roles ---

class UserRole(str, Enum):
    RECEIVER = "Receiver"
    SCHEDULER = "Scheduler"
    QA_INSPECTOR = "QAInspector"


# --- Status enums ---

class RecipeStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class ComponentLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class ProductionRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PENDING_QA = "PENDING_QA"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    CANCELLED = "CANCELLED"


class ComponentKind(str, Enum):
    INGREDIENT = "INGREDIENT"
    PACKAGING = "PACKAGING"
    LABEL = "LABEL"


class CheckweighVerdict(str, Enum):
    PASS = "PASS"
    UNDER = "UNDER"
    OVER = "OVER"


class CmrReason(str, Enum):
    CONSUME = "CONSUME"
    SCRAP_WASTE = "SCRAP_WASTE"
    RETURN_ON_CANCEL = "RETURN_ON_CANCEL"


# --- Entities with full common fields (id, created_at, updated_at, version) ---

class Customer(TypedDict):
    id: str
    name: str
    code: str
    owns_components: bool
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict):
    id: str
    customer_id: str
    sku: str
    name: str
    kind: str
    allergens: List[str]
    customer_owned: bool
    on_hand_qty: float
    reserved_qty: float
    created_at: str
    updated_at: str
    version: int


class ComponentLot(TypedDict):
    id: str
    component_id: str
    supplier_lot_code: str
    received_qty: float
    remaining_qty: float
    expiration_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict):
    id: str
    customer_id: str
    name: str
    target_fill_weight_g: float
    fill_tolerance_pct: float
    shelf_life_days: int
    allergen_profile: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BomLine(TypedDict):
    id: str
    recipe_id: str
    component_id: str
    qty_per_unit: float
    scrap_factor_pct: float
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict):
    id: str
    name: str
    rated_units_per_hour: float
    changeover_minutes: int
    current_allergen_residue: List[str]
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    rest_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    recipe_id: str
    line_id: str
    crew_id: str
    planned_units: int
    scheduled_start: str
    scheduled_end: str
    actual_units_good: int
    actual_units_scrapped: int
    lot_code: str
    pack_date: str
    fg_expiration_date: str
    run_rate_units_per_hour: float
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only records (id + created_at only) ---

class LotConsumption(TypedDict):
    id: str
    production_run_id: str
    component_lot_id: str
    bom_line_id: str
    consumed_qty: float
    customer_owned: bool
    created_at: str


class CheckweighSample(TypedDict):
    id: str
    production_run_id: str
    measured_weight_g: float
    verdict: str
    created_at: str


class CmrLedgerEntry(TypedDict):
    id: str
    customer_id: str
    component_id: str
    production_run_id: str
    delta_qty: float
    reason: str
    created_at: str


class SanitationEvent(TypedDict):
    id: str
    line_id: str
    cleared_allergens: List[str]
    created_at: str
