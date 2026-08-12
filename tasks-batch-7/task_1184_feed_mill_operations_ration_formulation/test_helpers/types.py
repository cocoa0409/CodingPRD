"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    MILL_MANAGER = "MillManager"
    NUTRITIONIST = "Nutritionist"
    OPERATOR = "Operator"
    QUALITY_TECH = "QualityTech"
    CUSTOMER = "Customer"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EmployeeCapability(str, Enum):
    OPERATOR = "OPERATOR"
    QUALITY_TECH = "QUALITY_TECH"
    DUAL = "DUAL"


class HazardClass(str, Enum):
    STANDARD = "STANDARD"
    MEDICATED = "MEDICATED"


class IngredientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ContractStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BinStatus(str, Enum):
    EMPTY = "EMPTY"
    READY = "READY"
    BLOCKED = "BLOCKED"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class OrderStatus(str, Enum):
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    REVISING = "REVISING"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ProductionLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"


class LineContamination(str, Enum):
    MEDICATED = "MEDICATED"
    NONE = "NONE"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    BATCHING = "BATCHING"
    MIXED = "MIXED"
    HOLD = "HOLD"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class WeighmentSource(str, Enum):
    CONTRACT = "CONTRACT"
    SPOT = "SPOT"


class WeighmentStatus(str, Enum):
    RECORDED = "RECORDED"
    VOID = "VOID"


class FlushRecordStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class SampleType(str, Enum):
    COMPOSITE = "COMPOSITE"
    RETAIN = "RETAIN"


class SampleResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class CargoClassCapability(str, Enum):
    STANDARD_ONLY = "STANDARD_ONLY"
    MEDICATED_CAPABLE = "MEDICATED_CAPABLE"


class CargoClass(str, Enum):
    STANDARD = "STANDARD"
    MEDICATED = "MEDICATED"


class TripStatus(str, Enum):
    PLANNED = "PLANNED"
    LOADING = "LOADING"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


# --- Entity records (common_fields: true -> id, created_at, updated_at, version) ---


class Customer(TypedDict, total=False):
    id: str
    name: str
    credit_limit_cents: int
    medicated_permit_ref: Optional[str]
    credit_used_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    full_name: str
    capability: str
    created_at: str
    updated_at: str
    version: int


class Ingredient(TypedDict, total=False):
    id: str
    code: str
    name: str
    hazard_class: str
    is_flush_material: bool
    crude_protein_pct: float
    crude_fiber_pct: float
    metabolizable_energy_kcal_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


# PriceTick is an immutable append-only market event (PRD §2.4):
# it carries ONLY id and created_at plus its input fields — no updated_at, no version.
class PriceTick(TypedDict, total=False):
    id: str
    ingredient_id: str
    price_cents_per_ton: int
    effective_from: str
    created_at: str


class Contract(TypedDict, total=False):
    id: str
    ingredient_id: str
    supplier_ref: str
    fixed_price_cents_per_ton: int
    total_tons: float
    consumed_tons: float
    remaining_tons: float
    window_start_date: str
    window_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bin(TypedDict, total=False):
    id: str
    code: str
    capacity_tons: float
    ingredient_id: Optional[str]
    on_hand_tons: float
    cumulative_replenished_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


class FormulaLine(TypedDict, total=False):
    ingredient_id: str
    inclusion_pct: float


class Formula(TypedDict, total=False):
    id: str
    code: str
    min_protein_pct: float
    max_fiber_pct: float
    min_energy_kcal_kg: float
    lines: List[FormulaLine]
    total_protein_pct: float
    total_fiber_pct: float
    total_energy_kcal_kg: float
    meets_constraints: bool
    provisional_cost_cents_per_ton: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict, total=False):
    id: str
    customer_id: str
    formula_id: str
    tons: float
    is_medicated: bool
    quoted_formula_version: int
    quoted_cost_basis_cents: int
    quoted_total_cents: int
    pinned_formula_version: Optional[int]
    pinned_lines: Optional[List[FormulaLine]]
    pinned_min_protein_pct: Optional[float]
    pinned_max_fiber_pct: Optional[float]
    final_total_cents: Optional[int]
    quote_stale: bool
    blocked: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionLine(TypedDict, total=False):
    id: str
    code: str
    status: str
    contamination: str
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict, total=False):
    id: str
    order_id: str
    line_id: str
    target_tons: float
    planned_start_at: str
    planned_end_at: str
    is_medicated: bool
    actual_tons: float
    ingredient_cost_cents: int
    mixed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Weighment(TypedDict, total=False):
    id: str
    batch_id: str
    ingredient_id: str
    bin_id: str
    actual_tons: float
    source: str
    contract_id: Optional[str]
    unit_price_cents: int
    line_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FlushRecord(TypedDict, total=False):
    id: str
    line_id: str
    flush_material_ingredient_id: str
    quantity_tons: float
    recorded_by_employee_id: str
    verified_by_employee_id: Optional[str]
    verified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualitySample(TypedDict, total=False):
    id: str
    batch_id: str
    sample_type: str
    retain_expiry_date: Optional[str]
    protein_pct_actual: Optional[float]
    crude_fiber_pct_actual: Optional[float]
    moisture_pct: Optional[float]
    protein_dry_matter: Optional[float]
    fiber_dry_matter: Optional[float]
    result: str
    result_by_employee_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Compartment(TypedDict, total=False):
    compartment_seq: int
    capacity_tons: float


class Truck(TypedDict, total=False):
    id: str
    plate_no: str
    cargo_class_capability: str
    compartments: List[Compartment]
    status: str
    created_at: str
    updated_at: str
    version: int


class CompartmentAllocation(TypedDict, total=False):
    compartment_seq: int
    tons: float
    cargo_class: str


class DeliveryTrip(TypedDict, total=False):
    id: str
    truck_id: str
    order_id: str
    planned_departure_at: str
    planned_return_at: str
    compartment_allocations: List[CompartmentAllocation]
    total_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int
