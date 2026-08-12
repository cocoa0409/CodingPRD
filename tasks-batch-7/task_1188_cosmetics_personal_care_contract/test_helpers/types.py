"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER_REP = "CustomerRep"
    FORMULATION_CHEMIST = "FormulationChemist"
    REGULATORY_AFFAIRS = "RegulatoryAffairs"
    QA_MANAGER = "QAManager"
    PRODUCTION_PLANNER = "ProductionPlanner"
    PLANT_DIRECTOR = "PlantDirector"


class CustomerTier(str, Enum):
    STANDARD = "STANDARD"
    PRESTIGE = "PRESTIGE"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class ReviewScope(str, Enum):
    INCI_LIST = "INCI_LIST"
    LABEL_ARTWORK = "LABEL_ARTWORK"


class ComponentKind(str, Enum):
    RAW_MATERIAL = "RAW_MATERIAL"
    BULK_FRAGRANCE = "BULK_FRAGRANCE"
    COLORANT = "COLORANT"
    PRIMARY_PACK = "PRIMARY_PACK"
    SECONDARY_PACK = "SECONDARY_PACK"


class SupplyMode(str, Enum):
    MANUFACTURER_SUPPLIED = "MANUFACTURER_SUPPLIED"
    CUSTOMER_SUPPLIED = "CUSTOMER_SUPPLIED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"


class SensorialProfile(str, Enum):
    WITHIN_SPEC = "WITHIN_SPEC"
    MINOR_VARIANT = "MINOR_VARIANT"


class VariantWaiver(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    WAIVED = "WAIVED"
    REJECTED = "REJECTED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    FILLING = "FILLING"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    MIXING = "MIXING"
    IPC_FAILED = "IPC_FAILED"
    IPC_PASSED = "IPC_PASSED"
    RELEASED_TO_FILLING = "RELEASED_TO_FILLING"
    CONSUMED = "CONSUMED"
    REJECTED = "REJECTED"


class CheckResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RoundResult(str, Enum):
    NONE = "NONE"
    PASS = "PASS"
    FAIL = "FAIL"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"


class ShortfallStatus(str, Enum):
    OPEN = "OPEN"
    COMMITMENT_RECEIVED = "COMMITMENT_RECEIVED"
    CLOSED_RESOLVED = "CLOSED_RESOLVED"
    ESCALATED = "ESCALATED"
    CLOSED_VOID = "CLOSED_VOID"


class LineStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    CLEANING = "CLEANING"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class StudyType(str, Enum):
    PRESERVATIVE_EFFICACY = "PRESERVATIVE_EFFICACY"
    ACCELERATED = "ACCELERATED"
    REAL_TIME = "REAL_TIME"


class StudyStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"


# --- Entity bodies (common_fields: true -> id + created_at + updated_at + version) ---


class Customer(TypedDict, total=False):
    id: str
    name: str
    tier: str
    minimum_run_units: int
    credit_limit_cents: int
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict, total=False):
    id: str
    customer_id: str
    base_formula_id: Optional[str]
    name: str
    version_seq: int
    ownership: str
    confidentiality: str
    product_class: str
    allergen_flag: bool
    bulk_mass_per_unit_kg: float
    viscosity_target_cps: int
    viscosity_tolerance_pct: float
    ph_target: float
    ph_tolerance: float
    ingredients: List[Dict[str, Any]]
    required_components: List[Dict[str, Any]]
    status: str
    cost_estimate_standard_per_kg_cents: int
    cost_estimate_current_lot_per_kg_cents: int
    created_at: str
    updated_at: str
    version: int


class RegulatoryReview(TypedDict, total=False):
    id: str
    formula_id: str
    review_scope: str
    status: str
    reviewer_user_id: Optional[str]
    comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict, total=False):
    id: str
    name: str
    kind: str
    supply_mode: str
    customer_id: Optional[str]
    standard_cost_per_kg_cents: float
    created_at: str
    updated_at: str
    version: int


class ComponentLot(TypedDict, total=False):
    id: str
    component_id: str
    lot_code: str
    quantity_received: float
    quantity_available: float
    quantity_reserved: float
    quantity_consumed: float
    unit_cost_per_kg_cents: Optional[float]
    expires_at: str
    sensorial_profile: str
    variant_waiver: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict, total=False):
    id: str
    customer_id: str
    formula_id: str
    formula_version_seq: Optional[int]
    requested_units: int
    forfeited_units: int
    filled_units: int
    open_units: int
    status: str
    hold_return_status: Optional[str]
    quote_total_cents: int
    fulfillable_units_conservative: int
    fulfillable_units_optimistic: int
    created_at: str
    updated_at: str
    version: int


class Batch(TypedDict, total=False):
    id: str
    production_order_id: str
    batch_size_kg: float
    scale_up_factor: float
    scale_up_approved: bool
    status: str
    failed_check_count: int
    round_viscosity_result: str
    round_ph_result: str
    last_ipc_recorded_by_user_id: Optional[str]
    batch_charge_cents: Optional[int]
    batch_charge_standard_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class IPCCheck(TypedDict, total=False):
    # Append-only quality record: id + created_at only (no updated_at, no version).
    id: str
    batch_id: str
    check_type: str
    measured_value: float
    round_index: int
    effective_tolerance: float
    result: str
    recorded_by_user_id: str
    created_at: str


class ComponentAllocation(TypedDict, total=False):
    id: str
    production_order_id: str
    batch_id: Optional[str]
    lot_id: str
    quantity: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ShortfallCase(TypedDict, total=False):
    id: str
    production_order_id: str
    component_id: str
    required_quantity: float
    allocatable_quantity: float
    shortfall_quantity: float
    status: str
    committed_by_date: Optional[str]
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FillingLine(TypedDict, total=False):
    id: str
    line_code: str
    status: str
    current_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FillingRun(TypedDict, total=False):
    id: str
    production_order_id: str
    line_id: str
    batch_id: str
    scheduled_start: str
    scheduled_end: str
    planned_units: int
    filled_units: Optional[int]
    rejected_units: int
    changeover_minutes_required: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StabilityChamber(TypedDict, total=False):
    id: str
    chamber_code: str
    capacity_studies: int
    active_study_count: int
    created_at: str
    updated_at: str
    version: int


class StabilityStudy(TypedDict, total=False):
    id: str
    formula_id: str
    chamber_id: str
    study_type: str
    required_intervals: List[int]
    recorded_interval_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StabilityReading(TypedDict, total=False):
    # Append-only quality record: id + created_at only (no updated_at, no version).
    id: str
    study_id: str
    interval_index: int
    result: str
    recorded_by_user_id: str
    created_at: str
