"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    EHS_OFFICER = "EHSOfficer"


class ProductForm(str, Enum):
    COATED = "COATED"
    BONDED = "BONDED"
    NONWOVEN = "NONWOVEN"


class ShelfLifePolicy(str, Enum):
    EXACT_DAY = "EXACT_DAY"
    END_OF_MONTH = "END_OF_MONTH"


class HazardClass(str, Enum):
    NONE = "NONE"
    METAL_SWARF = "METAL_SWARF"
    OIL_CONTAMINATED = "OIL_CONTAMINATED"


class GuardType(str, Enum):
    FIXED = "FIXED"
    ADJUSTABLE = "ADJUSTABLE"
    NONE = "NONE"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class MachineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"


class ConsumptionFlag(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"


class StandardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VarianceBand(str, Enum):
    UNDER = "UNDER"
    IN_BAND = "IN_BAND"
    OVER = "OVER"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class SubstitutionStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"


class BlanketOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReleaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_HOLD = "ON_HOLD"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class TrialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EVALUATION = "EVALUATION"
    CONVERTED = "CONVERTED"
    REJECTED = "REJECTED"


class DisposalMethod(str, Enum):
    RECYCLING = "RECYCLING"
    INCINERATION = "INCINERATION"
    LANDFILL = "LANDFILL"
    HAZARDOUS_WASTE_FACILITY = "HAZARDOUS_WASTE_FACILITY"


# --- Primary resources (common fields: id, created_at, updated_at, version) ---


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    product_form: str
    max_operating_speed_rpm: int
    shelf_life_months: Optional[int]
    shelf_life_policy: str
    used_media_hazard_class: str
    status: str
    replacement_product_id: Optional[str]
    discontinued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MachineAsset(TypedDict, total=False):
    id: str
    customer_ref: str
    asset_tag: str
    machine_type: str
    spindle_max_rpm: int
    guard_type: str
    status: str
    consumption_flag: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    product_id: str
    lot_code: str
    manufacture_date: str
    qty_received: int
    qty_on_hand: int
    expiry_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class UsageStandard(TypedDict, total=False):
    id: str
    machine_id: str
    product_id: str
    operation_name: str
    standard_qty_per_part: float
    effective_from: str
    effective_to: Optional[str]
    needs_review: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    customer_ref: str
    contract_number: str
    status: str
    term_start: str
    term_end: str
    price_hold_end: str
    escalation_pct: float
    escalation_effective_date: str
    created_at: str
    updated_at: str
    version: int


class ContractLine(TypedDict, total=False):
    id: str
    contract_id: str
    product_id: str
    base_unit_price_cents: int
    current_unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class BlanketOrder(TypedDict, total=False):
    id: str
    contract_id: str
    product_id: str
    committed_qty: int
    remaining_qty: Optional[int]
    substitution_status: str
    provisional_unit_price_cents: Optional[int]
    provisional_remaining_value_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict, total=False):
    lot_id: str
    qty: int


class Release(TypedDict, total=False):
    id: str
    blanket_order_id: str
    qty: int
    scheduled_ship_date: str
    provisional_unit_price_cents: int
    final_unit_price_cents: Optional[int]
    allocations: List[AllocationLine]
    billed_total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrialCase(TypedDict, total=False):
    id: str
    machine_id: str
    product_id: str
    incumbent_product_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    results_submitted_by_user_id: Optional[str]
    measured_removal_rate_g_per_min: Optional[float]
    parts_per_unit_media: Optional[float]
    cost_per_part_cents: Optional[int]
    converted_standard_id: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only events (id + created_at only; NO updated_at, NO version) ---


class UsageRecord(TypedDict, total=False):
    id: str
    machine_id: str
    product_id: str
    lot_id: str
    usage_date: str
    qty_used: int
    parts_produced: int
    actual_qty_per_part: float
    variance_pct: float
    variance_band: str
    created_at: str


class DisposalRecord(TypedDict, total=False):
    id: str
    customer_ref: str
    product_id: str
    lot_id: Optional[str]
    qty_disposed: int
    gross_weight_kg: float
    disposal_method: str
    manifest_number: Optional[str]
    certified_facility_ref: Optional[str]
    regulator_report_ref: Optional[str]
    disposed_at: str
    created_at: str
