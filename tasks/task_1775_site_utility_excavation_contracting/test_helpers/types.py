"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    PROJECT_MANAGER = "ProjectManager"
    FOREMAN = "Foreman"
    SAFETY_OFFICER = "SafetyOfficer"
    INSPECTOR = "Inspector"
    UTILITY_OWNER_REP = "UtilityOwnerRep"


class SoilClass(str, Enum):
    SOIL_A = "SOIL_A"
    SOIL_B = "SOIL_B"
    SOIL_C = "SOIL_C"


class OwnerType(str, Enum):
    WATER = "WATER"
    SEWER = "SEWER"
    GAS = "GAS"
    ELECTRIC = "ELECTRIC"
    TELECOM = "TELECOM"


class ExpectedUtilityType(str, Enum):
    WATER = "WATER"
    SEWER = "SEWER"
    GAS = "GAS"
    ELECTRIC = "ELECTRIC"
    TELECOM = "TELECOM"
    UNKNOWN = "UNKNOWN"


class PotholeMethod(str, Enum):
    VACUUM = "VACUUM"
    HAND_DIG = "HAND_DIG"


class PipeMaterial(str, Enum):
    PVC_C900 = "PVC_C900"
    DUCTILE_IRON = "DUCTILE_IRON"
    HDPE = "HDPE"
    RCP = "RCP"


class BeddingClass(str, Enum):
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"
    CLASS_D = "CLASS_D"


class ProtectiveSystem(str, Enum):
    SLOPING = "SLOPING"
    BENCHING = "BENCHING"
    SHORING = "SHORING"
    TRENCH_BOX = "TRENCH_BOX"


class ConditionType(str, Enum):
    ROCK = "ROCK"
    GROUNDWATER = "GROUNDWATER"
    CONTAMINATED_SOIL = "CONTAMINATED_SOIL"
    CONFLICTING_UTILITY = "CONFLICTING_UTILITY"
    VOID = "VOID"


class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class WorkPosture(str, Enum):
    CLEAR = "CLEAR"
    STOPPED = "STOPPED"


class LocateTicketStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class PotholeStatus(str, Enum):
    PLANNED = "PLANNED"
    PERFORMED = "PERFORMED"
    VERIFIED = "VERIFIED"
    CONFLICT = "CONFLICT"
    SUPERSEDED = "SUPERSEDED"


class TrenchPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class PipeSegmentStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    INSTALLING = "INSTALLING"
    INSTALLED = "INSTALLED"
    BACKFILLING = "BACKFILLING"
    COMPLETE = "COMPLETE"
    ON_HOLD = "ON_HOLD"


class HoldReason(str, Enum):
    NONE = "NONE"
    STOP_WORK = "STOP_WORK"
    DEWATERING = "DEWATERING"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class InspectionStatus(str, Enum):
    RECORDED = "RECORDED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"


class ShutdownWindowStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class DischargePermitStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class DischargeClassification(str, Enum):
    NORMAL = "NORMAL"
    EXCEEDS_FLOW = "EXCEEDS_FLOW"
    EXCEEDS_TURBIDITY = "EXCEEDS_TURBIDITY"
    EXCEEDS_VOLUME = "EXCEEDS_VOLUME"


class CompactionTestStatus(str, Enum):
    RECORDED = "RECORDED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AsBuiltStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ConditionStatus(str, Enum):
    OPEN = "OPEN"
    MITIGATING = "MITIGATING"
    RESOLVED = "RESOLVED"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"


class ChangeOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


# --- Entity payloads (common_fields entities carry id/created_at/updated_at/version) ---


class Project(TypedDict, total=False):
    id: str
    name: str
    contract_ref: str
    soil_class_default: str
    contingency_cents: int
    single_co_cap_cents: int
    status: str
    work_posture: str
    approved_co_total_cents: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UtilityOwner(TypedDict, total=False):
    id: str
    name: str
    owner_type: str
    min_notice_hours: int
    max_shutdown_hours: int
    committed_shutdown_minutes: int
    created_at: str
    updated_at: str
    version: int


class LocateTicket(TypedDict, total=False):
    id: str
    project_id: str
    ticket_number: str
    legal_start_at: str
    valid_until: str
    status: str
    renew_count: int
    created_at: str
    updated_at: str
    version: int


class PotholeVerification(TypedDict, total=False):
    id: str
    project_id: str
    locate_ticket_id: str
    station_label: str
    expected_utility_type: str
    method: str
    design_depth_in: int
    design_offset_in: int
    measured_depth_in: Optional[int]
    measured_offset_in: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PipeSegment(TypedDict, total=False):
    id: str
    project_id: str
    utility_owner_id: str
    segment_label: str
    pipe_material: str
    diameter_in: int
    length_ft: float
    bedding_class: str
    design_invert_depth_ft: float
    design_slope_pct: float
    requires_dewatering: bool
    lifts_required: int
    lifts_satisfied: int
    avg_compaction_pct: Optional[float]
    min_compaction_pct: Optional[float]
    hold_reason: str
    resume_status: Optional[str]
    tie_in_completed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TrenchSafetyPlan(TypedDict, total=False):
    id: str
    project_id: str
    pipe_segment_id: str
    max_depth_ft: float
    soil_class: str
    protective_system: str
    slope_ratio: Optional[float]
    engineered_certification: bool
    revision: int
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallationInspection(TypedDict, total=False):
    id: str
    pipe_segment_id: str
    bedding_ok: bool
    joint_ok: bool
    slope_measured_pct: float
    cover_depth_ft: float
    result: str
    recorded_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ShutdownWindow(TypedDict, total=False):
    id: str
    project_id: str
    utility_owner_id: str
    pipe_segment_id: str
    window_start: str
    window_end: str
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DischargePermit(TypedDict, total=False):
    id: str
    project_id: str
    permit_number: str
    max_flow_gpm: int
    turbidity_limit_ntu: int
    daily_volume_limit_gal: int
    effective_from: str
    effective_to: str
    exceedance_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DischargeReading(TypedDict, total=False):
    id: str
    discharge_permit_id: str
    recorded_at: str
    flow_gpm: int
    turbidity_ntu: int
    duration_min: int
    volume_gal: int
    classification: str
    created_at: str
    updated_at: str
    version: int


class CompactionTest(TypedDict, total=False):
    id: str
    pipe_segment_id: str
    lift_number: int
    proctor_max_density_pcf: float
    field_density_pcf: float
    moisture_pct: float
    compaction_pct: float
    required_pct: float
    result: str
    recorded_by_user_id: str
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AsBuiltPackage(TypedDict, total=False):
    id: str
    pipe_segment_id: str
    surveyor_stamp: str
    measured_length_ft: float
    measured_invert_ft: float
    length_variance_ft: float
    invert_variance_ft: float
    within_tolerance: bool
    revision: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UnforeseenCondition(TypedDict, total=False):
    id: str
    project_id: str
    pipe_segment_id: Optional[str]
    condition_type: str
    stop_work_required: bool
    description: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChangeOrder(TypedDict, total=False):
    id: str
    project_id: str
    unforeseen_condition_id: str
    utility_owner_id: str
    revision: int
    labor_hours: float
    labor_rate_cents: int
    equipment_hours: float
    equipment_rate_cents: int
    material_cost_cents: int
    direct_cost_cents: int
    markup_cents: int
    provisional_price_cents: int
    final_price_cents: Optional[int]
    price_delta_cents: Optional[int]
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit record: carries only id + created_at from the common set
# (PRD §2.4) — no updated_at, no version.
class AuditEvent(TypedDict, total=False):
    id: str
    created_at: str
    project_id: str
    actor_role: str
    actor_user_id: str
    action: str
    entity_type: str
    entity_id: str
    detail: str
