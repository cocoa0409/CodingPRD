"""Domain types for the thermoforming plant API.

Entity shapes follow PRD §3 (per-resource fields) and PRD §2.4 (common system
fields): primary resources carry id/created_at/updated_at/version; scrap records
and cleanliness certificates are append-only and carry only id/created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    MATERIALS_PLANNER = "MaterialsPlanner"
    TOOLING_ENGINEER = "ToolingEngineer"
    PACKAGING_ENGINEER = "PackagingEngineer"
    PLANT_MANAGER = "PlantManager"
    PRODUCTION_SCHEDULER = "ProductionScheduler"
    QUALITY_INSPECTOR = "QualityInspector"
    ANY = "Any"


class ResinType(str, Enum):
    PETG = "PETG"
    HIPS = "HIPS"
    ABS = "ABS"
    PP = "PP"
    PC = "PC"


class CleanlinessGrade(str, Enum):
    INDUSTRIAL = "INDUSTRIAL"
    FOOD = "FOOD"
    MEDICAL = "MEDICAL"


class MaterialLotStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    CERTIFIED = "CERTIFIED"
    DEPLETED = "DEPLETED"
    BLOCKED = "BLOCKED"


class RegrindBatchStatus(str, Enum):
    ACCEPTING = "ACCEPTING"
    PENDING_CERT = "PENDING_CERT"
    CERTIFIED = "CERTIFIED"
    DOWNGRADED = "DOWNGRADED"
    REJECTED = "REJECTED"


class ToolStatus(str, Enum):
    DRAFT = "DRAFT"
    PROTOTYPE = "PROTOTYPE"
    QUALIFICATION = "QUALIFICATION"
    PRODUCTION = "PRODUCTION"
    UNDER_REVISION = "UNDER_REVISION"


class ToolType(str, Enum):
    FORM_MOLD = "FORM_MOLD"
    TRIM_FIXTURE = "TRIM_FIXTURE"
    MATCHED_SET = "MATCHED_SET"


class PackagingSpecStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SpecType(str, Enum):
    STOCK = "STOCK"
    CUSTOM = "CUSTOM"


class OrderScheduleStatus(str, Enum):
    QUEUED = "QUEUED"
    STAGED = "STAGED"
    RUNNING = "RUNNING"
    ON_HOLD = "ON_HOLD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderQualityStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    REWORK_HOLD = "REWORK_HOLD"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    REVIEW = "REVIEW"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class AllocationSourceType(str, Enum):
    VIRGIN_LOT = "VIRGIN_LOT"
    REGRIND = "REGRIND"


class ResourceType(str, Enum):
    FORMING_STATION = "FORMING_STATION"
    INSPECTION_BOOTH = "INSPECTION_BOOTH"


class FormingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class ScrapRecordStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class InspectionType(str, Enum):
    FIRST_ARTICLE = "FIRST_ARTICLE"
    FINAL = "FINAL"


class InspectionStatus(str, Enum):
    RECORDED = "RECORDED"
    DISPOSITIONED = "DISPOSITIONED"


class Disposition(str, Enum):
    PASS = "PASS"
    REWORK = "REWORK"
    SCRAP = "SCRAP"


class TaskType(str, Enum):
    TRIM = "TRIM"
    INSERT = "INSERT"
    BOND = "BOND"
    PACK = "PACK"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class CertSubjectType(str, Enum):
    MATERIAL_LOT = "MATERIAL_LOT"
    REGRIND_BATCH = "REGRIND_BATCH"
    TOOL = "TOOL"
    PACKAGING_SPEC = "PACKAGING_SPEC"


class BatchDecision(str, Enum):
    CERTIFIED = "CERTIFIED"
    DOWNGRADED = "DOWNGRADED"
    REJECTED = "REJECTED"


class SpecDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ScrapDecision(str, Enum):
    CERTIFY = "CERTIFY"
    REJECT = "REJECT"


# --- Entity TypedDicts (PRD §2.4 common fields + §3 per-resource fields) ---

class MaterialLot(TypedDict, total=False):
    id: str
    lot_code: str
    resin_type: str
    gauge_mm: float
    cleanliness_grade_required: str
    quantity_kg: float
    unit_cost_per_kg: float
    allocated_kg: float
    consumed_kg: float
    available_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RegrindBatch(TypedDict, total=False):
    id: str
    batch_code: str
    resin_type: str
    source_grade: str
    target_kg: float
    accumulated_kg: float
    reserved_kg: float
    consumed_kg: float
    available_kg: float
    certified_grade: Optional[str]
    max_blend_pct: Optional[float]
    created_by_user_id: str
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Tool(TypedDict, total=False):
    id: str
    tool_code: str
    part_number: str
    tool_type: str
    min_gauge_mm: float
    max_gauge_mm: float
    cleanliness_grade: str
    prototype_cost: float
    production_cost: Optional[float]
    rated_lifetime_shots: Optional[int]
    shots_used: int
    drawing_revision: int
    qualified_drawing_revision: Optional[int]
    proto_shot_limit: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PackagingSpec(TypedDict, total=False):
    id: str
    spec_code: str
    spec_type: str
    cleanliness_grade: str
    per_pack_cost: float
    decided_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict, total=False):
    id: str
    order_code: str
    part_number: str
    resin_type: str
    ordered_qty: int
    required_gauge_mm: float
    cleanliness_grade: str
    is_prototype_order: bool
    spec_nominal_wall_mm: float
    spec_min_wall_mm: float
    nominal_part_weight_kg: float
    std_cycle_time_s: int
    std_machine_rate_per_hour: float
    tool_id: str
    packaging_spec_id: str
    required_material_kg: float
    shots_completed: int
    shots_scrapped: int
    provisional_cost: Optional[float]
    tooling_charge: Optional[float]
    final_cost: Optional[float]
    schedule_status: str
    quality_status: str
    created_at: str
    updated_at: str
    version: int


class MaterialAllocation(TypedDict, total=False):
    id: str
    production_order_id: str
    source_type: str
    lot_id: Optional[str]
    regrind_batch_id: Optional[str]
    qty_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MachineResource(TypedDict, total=False):
    id: str
    resource_code: str
    resource_type: str
    cleanliness_grade: str
    machine_rate_per_hour: float
    created_at: str
    updated_at: str
    version: int


class FormingRun(TypedDict, total=False):
    id: str
    production_order_id: str
    station_id: str
    planned_start: str
    planned_end: str
    oven_temp_c: float
    cycle_time_s: int
    shots_planned: int
    shots_completed: Optional[int]
    scrap_weight_kg: Optional[float]
    actual_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScrapRecord(TypedDict, total=False):
    # Append-only audit record (PRD §2.4): only id + created_at system fields.
    id: str
    forming_run_id: str
    regrind_batch_id: Optional[str]
    resin_type: str
    weight_kg: float
    status: str
    created_at: str


class QualityInspection(TypedDict, total=False):
    id: str
    production_order_id: str
    forming_run_id: Optional[str]
    booth_id: str
    inspection_type: str
    scheduled_start: str
    scheduled_end: str
    wall_measurements_mm: List[float]
    min_wall_mm: float
    avg_wall_mm: float
    deviation_pct: float
    disposition: Optional[str]
    scrapped_qty: Optional[int]
    recorded_by_user_id: str
    dispositioned_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AssemblyTask(TypedDict, total=False):
    id: str
    production_order_id: str
    task_type: str
    sequence_no: int
    insert_part_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CleanlinessCertificate(TypedDict, total=False):
    # Append-only record (PRD §2.4): only id + created_at system fields.
    id: str
    subject_type: str
    subject_id: str
    grade: str
    issued_at: str
    expires_at: str
    cert_body: str
    created_at: str


__all__ = [
    "UserRole",
    "ResinType",
    "CleanlinessGrade",
    "MaterialLotStatus",
    "RegrindBatchStatus",
    "ToolStatus",
    "ToolType",
    "PackagingSpecStatus",
    "SpecType",
    "OrderScheduleStatus",
    "OrderQualityStatus",
    "AllocationStatus",
    "AllocationSourceType",
    "ResourceType",
    "FormingRunStatus",
    "ScrapRecordStatus",
    "InspectionType",
    "InspectionStatus",
    "Disposition",
    "TaskType",
    "TaskStatus",
    "CertSubjectType",
    "BatchDecision",
    "SpecDecision",
    "ScrapDecision",
    "MaterialLot",
    "RegrindBatch",
    "Tool",
    "PackagingSpec",
    "ProductionOrder",
    "MaterialAllocation",
    "MachineResource",
    "FormingRun",
    "ScrapRecord",
    "QualityInspection",
    "AssemblyTask",
    "CleanlinessCertificate",
]
