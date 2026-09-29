"""Entity shapes, status enums and the role enum for the assembly plant API.

The TypedDicts are documentation-grade: they name exactly the fields the PRD
declares for each entity so tests can be read without cross-referencing.
"""

from enum import Enum
from typing import Optional, TypedDict


# =============================================================================
# Roles
# =============================================================================
class Role(str, Enum):
    """The seven roles the API recognizes."""

    PLANT_ADMIN = "PlantAdmin"
    PRODUCTION_PLANNER = "ProductionPlanner"
    LINE_OPERATOR = "LineOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    ENGINEERING_LEAD = "EngineeringLead"
    WARRANTY_ANALYST = "WarrantyAnalyst"
    SUPPLIER_PORTAL = "SupplierPortal"


#: The six plant-internal roles, whose X-User-ID is opaque.
PLANT_INTERNAL_ROLES = (
    Role.PLANT_ADMIN,
    Role.PRODUCTION_PLANNER,
    Role.LINE_OPERATOR,
    Role.QUALITY_INSPECTOR,
    Role.ENGINEERING_LEAD,
    Role.WARRANTY_ANALYST,
)


# =============================================================================
# Status enums
# =============================================================================
class LineOperatingMode(str, Enum):
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class LinePosture(str, Enum):
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    STOPPED = "STOPPED"


class ModelVariantStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    OBSOLETE = "OBSOLETE"


class SupplierStatus(str, Enum):
    APPROVED = "APPROVED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class PartLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CHANGE_PENDING = "CHANGE_PENDING"
    SERVICE_ONLY = "SERVICE_ONLY"
    OBSOLETE = "OBSOLETE"


class BomLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class DeliveryCallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ARRIVED_ON_TIME = "ARRIVED_ON_TIME"
    ARRIVED_LATE = "ARRIVED_LATE"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    PLANNER = "PLANNER"
    SUPPLIER_PROBATION = "SUPPLIER_PROBATION"
    PART_SERVICE_ONLY = "PART_SERVICE_ONLY"


class ShiftPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ShiftCode(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class BuildSlotStatus(str, Enum):
    PLANNED = "PLANNED"
    SEQUENCED = "SEQUENCED"
    RELEASED = "RELEASED"
    BUILT = "BUILT"
    CANCELLED = "CANCELLED"


class AssemblyStatus(str, Enum):
    IN_STATION = "IN_STATION"
    ASSEMBLED = "ASSEMBLED"
    REWORK = "REWORK"
    SHIPPED = "SHIPPED"


class QualityStatus(str, Enum):
    PENDING = "PENDING"
    SAFETY_PASSED = "SAFETY_PASSED"
    GATED = "GATED"
    CERTIFIED = "CERTIFIED"
    QUARANTINED = "QUARANTINED"


class CertificationTier(str, Enum):
    A_PLUS = "A_PLUS"
    A = "A"
    B = "B"


class TestType(str, Enum):
    ELECTRICAL_SAFETY = "ELECTRICAL_SAFETY"
    LEAK = "LEAK"
    FUNCTIONAL_CYCLE = "FUNCTIONAL_CYCLE"
    ENERGY = "ENERGY"
    WATER = "WATER"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    MEASURED = "MEASURED"


class QualityTestStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class EngineeringChangeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CUT_IN = "CUT_IN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ChangeOrigin(str, Enum):
    MANUAL = "MANUAL"
    WARRANTY = "WARRANTY"


class ChangeDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


class WarrantyReturnStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TEARDOWN = "TEARDOWN"
    ANALYZED_DESIGN = "ANALYZED_DESIGN"
    ANALYZED_SUPPLIER = "ANALYZED_SUPPLIER"
    CLOSED = "CLOSED"


class Disposition(str, Enum):
    DESIGN_DEFECT = "DESIGN_DEFECT"
    SUPPLIER_DEFECT = "SUPPLIER_DEFECT"
    NO_FAULT_FOUND = "NO_FAULT_FOUND"


#: The literal user id the API records when it mints a change by itself.
SYSTEM_USER_ID = "system"


# =============================================================================
# Entity shapes
# =============================================================================
class Line(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    line_code: str
    takt_seconds: int
    option_load_limit_pct: float
    baseline_headcount: int
    current_family_code: str
    operating_mode: str
    stop_reason: Optional[str]
    changeover_count: int
    checkpoint_index: int
    max_released_sequence_index: int
    presentation_slots_total: int
    presentation_slots_committed: int
    free_slot_pct: float
    posture: str


class Station(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    line_id: str
    station_code: str
    position_index: int
    presentation_slot_capacity: int
    station_cycle_seconds: int
    presentation_slots_used: int


class ModelVariant(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    model_code: str
    family_code: str
    option_codes: list
    option_content_points: int
    labor_minutes: int
    functional_cycle_count_required: int
    requires_leak_test: bool
    hipot_leakage_ma_limit: Optional[float]
    leak_limit_ml_per_min: Optional[float]
    energy_kwh_limit: Optional[float]
    water_liters_limit: Optional[float]
    status: str


class Supplier(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    supplier_code: str
    name: str
    sync_window_minutes: int
    status: str
    on_time_score: float
    delivered_on_time_count: int
    delivered_late_count: int
    missed_count: int
    quality_penalty_count: int


class Part(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    part_number: str
    supplier_id: str
    is_sequenced_module: bool
    line_side_max_units: int
    lifecycle_status: str
    field_failure_count: int
    cohort_failure_rate_per_1000: float
    service_obligation_until: Optional[str]


class BomLine(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    model_variant_id: str
    part_id: str
    station_id: str
    bom_position_code: str
    qty_per_unit: int
    effective_from_sequence: int
    status: str
    superseded_by_bom_line_id: Optional[str]
    created_by_change_id: Optional[str]


class DeliveryCall(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    supplier_id: str
    part_id: str
    station_id: str
    window_start: str
    window_end: str
    sequenced_qty: int
    status: str
    arrived_at: Optional[str]
    lateness_minutes: Optional[int]
    cancel_reason: Optional[str]


class ShiftPlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    line_id: str
    shift_date: str
    shift_code: str
    planned_headcount: int
    shift_start: str
    shift_end: str
    overtime_minutes: int
    available_labor_minutes: int
    unit_labor_minutes: int
    changeover_minutes: int
    committed_labor_minutes: int
    status: str


class PresentationAllocation(TypedDict):
    station_id: str
    slot_units: int


class BuildSlot(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    line_id: str
    model_variant_id: str
    sequence_index: int
    planned_start: str
    status: str
    shift_plan_id: Optional[str]
    sync_delivery_call_id: Optional[str]
    option_points_snapshot: Optional[int]
    labor_minutes_snapshot: Optional[int]
    presentation_allocations: list
    allocated_slot_units: int


class ProductionUnit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    build_slot_id: str
    model_variant_id: str
    line_id: str
    serial_number: str
    built_at_sequence_index: int
    assembly_status: str
    quality_status: str
    rework_count: int
    provisional_efficiency_index: Optional[float]
    efficiency_index: Optional[float]
    certification_tier: Optional[str]


class QualityTest(TypedDict):
    """The single entity that carries no `updated_at` and no `version`."""

    id: str
    created_at: str
    production_unit_id: str
    test_type: str
    measured_value: float
    limit_value: Optional[float]
    result: str
    status: str


class EngineeringChange(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    model_variant_id: str
    bom_position_code: str
    affected_part_id: str
    replacement_part_id: Optional[str]
    new_qty_per_unit: Optional[int]
    target_line_id: str
    cut_in_sequence_index: int
    status: str
    origin: str
    revision_round: int
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    cut_in_at: Optional[str]
    source_warranty_return_id: Optional[str]


class WarrantyReturn(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    production_unit_id: str
    failure_code: str
    field_hours: float
    returned_at: str
    status: str
    teardown_started_at: Optional[str]
    disposition: Optional[str]
    root_cause_part_id: Optional[str]
    engineering_change_id: Optional[str]
    design_feedback_note: Optional[str]
