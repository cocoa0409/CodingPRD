"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    TOOLING_ENGINEER = "ToolingEngineer"
    LAMINATOR = "Laminator"
    CURE_TECHNICIAN = "CureTechnician"
    QUALITY_INSPECTOR = "QualityInspector"
    EHS_OFFICER = "EHSOfficer"


class EmissionPermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CLOSED = "CLOSED"


class MoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE_DUE = "MAINTENANCE_DUE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    RETIRED = "RETIRED"


class ToolingPhase(str, Enum):
    PROTOTYPE = "PROTOTYPE"
    TRANSITION = "TRANSITION"
    PRODUCTION = "PRODUCTION"


class PlyBookStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class WorkOrderStatus(str, Enum):
    RELEASED = "RELEASED"
    LAYUP_IN_PROGRESS = "LAYUP_IN_PROGRESS"
    AWAITING_CURE = "AWAITING_CURE"
    CURE_SCHEDULED = "CURE_SCHEDULED"
    IN_CURE = "IN_CURE"
    CURED = "CURED"
    IN_INSPECTION = "IN_INSPECTION"
    REPAIR = "REPAIR"
    ACCEPTED = "ACCEPTED"
    SCRAPPED = "SCRAPPED"


class ScrapReason(str, Enum):
    WEIGHT_OUT_OF_TOLERANCE = "WEIGHT_OUT_OF_TOLERANCE"
    INSPECTION_FAIL = "INSPECTION_FAIL"
    MANUAL = "MANUAL"


class ResinSystem(str, Enum):
    POLYESTER = "POLYESTER"
    VINYL_ESTER = "VINYL_ESTER"
    EPOXY = "EPOXY"


class ResinBatchStatus(str, Enum):
    MIXED = "MIXED"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    QUENCHED = "QUENCHED"
    REJECTED = "REJECTED"


class LayupSessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class EquipmentKind(str, Enum):
    OVEN = "OVEN"
    AUTOCLAVE = "AUTOCLAVE"


class CureEquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CureCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class InspectionMethod(str, Enum):
    ULTRASONIC = "ULTRASONIC"
    TAP_TEST = "TAP_TEST"
    VISUAL = "VISUAL"


class InspectionResult(str, Enum):
    PASS = "PASS"
    REPAIR_REQUIRED = "REPAIR_REQUIRED"
    FAIL = "FAIL"


class RepairStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


# All entities carry the common resource properties of PRD §2.4
# (id, created_at, updated_at, version); there are no append-only entities.


class EmissionPermit(TypedDict, total=False):
    id: str
    permit_code: str
    period_start: str
    period_end: str
    styrene_quota_kg: float
    warning_threshold_pct: float
    styrene_used_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Mold(TypedDict, total=False):
    id: str
    mold_code: str
    tooling_phase: str
    maintenance_interval_cycles: int
    cycles_since_maintenance: int
    prototype_parts_required: int
    prototype_parts_validated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ply(TypedDict, total=False):
    seq: int
    material_code: str
    orientation_deg: float
    areal_weight_g_m2: float


class PlyBook(TypedDict, total=False):
    id: str
    part_number: str
    revision: str
    part_area_m2: float
    plies: List[Ply]
    resin_system: str
    target_fiber_volume_pct: float
    tolerance_pct: float
    max_repair_attempts: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    work_order_no: str
    part_number: str
    mold_id: str
    ply_book_id: str
    pinned_ply_book_version: int
    quantity: int
    due_date: str
    target_part_weight_g: float
    actual_part_weight_g: float
    weight_deviation_pct: float
    layup_started_at: Optional[str]
    demolded_at: Optional[str]
    repair_count: int
    scrap_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ResinBatch(TypedDict, total=False):
    id: str
    batch_code: str
    resin_system: str
    resin_mass_g: float
    catalyst_mass_g: float
    target_ratio_pct: float
    ratio_tolerance_pct: float
    actual_ratio_pct: float
    nominal_pot_life_minutes: int
    ambient_temp_c: Optional[float]
    effective_pot_life_minutes: int
    mixed_at: str
    expires_at: str
    total_mass_g: float
    consumed_mass_g: float
    remaining_mass_g: float
    quenched_mass_g: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LayupSession(TypedDict, total=False):
    id: str
    work_order_id: str
    resin_batch_id: str
    permit_id: str
    resin_used_g: float
    styrene_emitted_kg: float
    laminator_id: str
    session_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CureEquipment(TypedDict, total=False):
    id: str
    equipment_code: str
    kind: str
    max_parts_per_cycle: int
    turnaround_minutes: int
    max_temperature_c: float
    max_pressure_bar: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CureCycle(TypedDict, total=False):
    id: str
    work_order_id: str
    equipment_id: str
    ramp_rate_c_per_min: float
    soak_temp_c: float
    soak_minutes: int
    pressure_bar: Optional[float]
    scheduled_start: str
    scheduled_end: str
    uses_mold: bool
    recorded_min_temp_c: float
    recorded_max_temp_c: float
    recorded_soak_minutes: int
    recorded_ramp_rate_c_per_min: float
    cure_deviation_score: float
    cure_log_ok: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    work_order_id: str
    inspector_id: str
    method: str
    void_content_pct: float
    delamination_area_cm2: float
    result: str
    inspected_at: str
    created_repair_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Repair(TypedDict, total=False):
    id: str
    work_order_id: str
    source_inspection_id: str
    repair_seq: int
    status: str
    created_at: str
    updated_at: str
    version: int
