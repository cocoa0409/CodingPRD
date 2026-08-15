"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §4)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    VDC_MANAGER = "VDCManager"
    BIM_COORDINATOR = "BIMCoordinator"
    TRADE_MODEL_AUTHOR = "TradeModelAuthor"
    LEAD_ENGINEER = "LeadEngineer"
    FABRICATION_LEAD = "FabricationLead"
    FACILITIES_MANAGER = "FacilitiesManager"


class ProjectPhase(str, Enum):
    SCHEMATIC_DESIGN = "SCHEMATIC_DESIGN"
    DESIGN_DEVELOPMENT = "DESIGN_DEVELOPMENT"
    CONSTRUCTION_DOCUMENTS = "CONSTRUCTION_DOCUMENTS"
    CONSTRUCTION_ADMINISTRATION = "CONSTRUCTION_ADMINISTRATION"
    CLOSEOUT = "CLOSEOUT"


class CoordinationPosture(str, Enum):
    NORMAL = "NORMAL"
    COORDINATION_HOLD = "COORDINATION_HOLD"


class Discipline(str, Enum):
    ARCHITECTURAL = "ARCHITECTURAL"
    STRUCTURAL = "STRUCTURAL"
    MECHANICAL = "MECHANICAL"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    FIRE_PROTECTION = "FIRE_PROTECTION"


class SoftwarePlatform(str, Enum):
    REVIT = "REVIT"
    TEKLA = "TEKLA"
    ARCHICAD = "ARCHICAD"
    IFC_ONLY = "IFC_ONLY"


class FileFormat(str, Enum):
    RVT = "RVT"
    IFC = "IFC"
    NWC = "NWC"
    DWG = "DWG"


class InteropStatus(str, Enum):
    NATIVE = "NATIVE"
    CONVERTIBLE = "CONVERTIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"


class TradePartnerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"


class TradeModelStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class FederatedModelStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSEMBLED = "ASSEMBLED"
    FROZEN = "FROZEN"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"


class FreezeWindowPurpose(str, Enum):
    COORDINATION_FREEZE = "COORDINATION_FREEZE"
    FABRICATION_HOLD = "FABRICATION_HOLD"
    HANDOVER_FREEZE = "HANDOVER_FREEZE"


class ClashRunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class ClashSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class ClashIssueStatus(str, Enum):
    NEW = "NEW"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    ADJOURNED = "ADJOURNED"


class CommitmentStatus(str, Enum):
    COMMITTED = "COMMITTED"
    FULFILLED = "FULFILLED"
    BREACHED = "BREACHED"
    WAIVED = "WAIVED"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNOFF_IN_PROGRESS = "SIGNOFF_IN_PROGRESS"
    READY_FOR_RELEASE = "READY_FOR_RELEASE"
    RELEASED = "RELEASED"
    VOID = "VOID"


class SignOffStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SIGNED = "SIGNED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class AsBuiltStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FIELD_VERIFIED = "FIELD_VERIFIED"
    REJECTED = "REJECTED"


class TakeoffStatus(str, Enum):
    EXTRACTED = "EXTRACTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class HandoverStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    READY = "READY"
    TRANSMITTED = "TRANSMITTED"
    FM_ACCEPTED = "FM_ACCEPTED"
    FM_REJECTED = "FM_REJECTED"


# All resources carry the four common fields of PRD §2.4
# (id, created_at, updated_at, version).


class Project(TypedDict, total=False):
    id: str
    name: str
    current_phase: str
    coordination_posture: str
    coordination_readiness_index: int
    open_critical_count: int
    open_major_count: int
    unassigned_minor_count: int
    overdue_commitment_count: int
    ops_sweep_index: int
    created_at: str
    updated_at: str
    version: int


class LodRequirement(TypedDict, total=False):
    id: str
    project_id: str
    discipline: str
    phase: str
    min_lod: int
    clearance_requirement_mm: float
    created_at: str
    updated_at: str
    version: int


class TradePartner(TypedDict, total=False):
    id: str
    project_id: str
    company_name: str
    discipline: str
    hourly_rate_cents: int
    coordination_budget_hours: float
    consumed_resolution_hours: float
    reliability_score: float
    breach_count: int
    software_platform: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeModel(TypedDict, total=False):
    id: str
    project_id: str
    trade_partner_id: str
    discipline: str
    revision_number: int
    file_format: str
    interop_status: str
    declared_lod: int
    life_safety_elements: int
    life_safety_compliant: int
    envelope_elements: int
    envelope_compliant: int
    finish_elements: int
    finish_compliant: int
    submission_score: Optional[float]
    audit_score: Optional[float]
    supersedes_model_id: Optional[str]
    submitted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FederatedModel(TypedDict, total=False):
    id: str
    project_id: str
    label: str
    assembly_index: int
    target_format: str
    status: str
    is_stale: bool
    open_critical_count: int
    created_at: str
    updated_at: str
    version: int


class FederatedModelMember(TypedDict, total=False):
    id: str
    federated_model_id: str
    trade_model_id: str
    discipline: str
    pinned_model_version: int
    created_at: str
    updated_at: str
    version: int


class FreezeWindow(TypedDict, total=False):
    id: str
    federated_model_id: str
    starts_at: str
    ends_at: str
    purpose: str
    created_at: str
    updated_at: str
    version: int


class ClashDetectionRun(TypedDict, total=False):
    id: str
    project_id: str
    federated_model_id: str
    run_index: int
    tolerance_mm: float
    status: str
    total_clash_count: int
    open_clash_count: int
    closed_clash_count: int
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClashIssue(TypedDict, total=False):
    id: str
    clash_run_id: str
    federated_model_id: str
    element_pair: str
    overlap_mm: float
    spans_disciplines: bool
    severity: str
    assigned_trade_partner_id: Optional[str]
    assigned_by_user_id: Optional[str]
    provisional_cost_cents: Optional[int]
    actual_labor_hours: Optional[float]
    resolved_by_user_id: Optional[str]
    actual_cost_cents: Optional[int]
    cycle_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoordinationMeeting(TypedDict, total=False):
    id: str
    project_id: str
    room_id: str
    starts_at: str
    ends_at: str
    status: str
    commitment_count: int
    fulfilled_commitment_count: int
    breached_commitment_count: int
    created_at: str
    updated_at: str
    version: int


class ResolutionCommitment(TypedDict, total=False):
    id: str
    meeting_id: str
    clash_issue_id: str
    committed_by_partner_id: str
    due_at: str
    status: str
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FabricationPackage(TypedDict, total=False):
    id: str
    project_id: str
    federated_model_id: str
    requesting_partner_id: str
    scope_disciplines: list
    required_signoff_count: int
    signed_count: int
    pinned_fed_model_version: int
    status: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SignOff(TypedDict, total=False):
    id: str
    fabrication_package_id: str
    discipline: str
    trade_model_id: str
    pinned_model_version: int
    signer_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AsBuiltModel(TypedDict, total=False):
    id: str
    project_id: str
    trade_model_id: str
    trade_partner_id: str
    field_verification_notes: str
    verification_deviation_mm: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class QuantityTakeoff(TypedDict, total=False):
    id: str
    project_id: str
    federated_model_id: str
    extraction_mode: str
    discipline_filter: Optional[str]
    elements: list
    element_count: int
    total_quantity: float
    status: str
    created_at: str
    updated_at: str
    version: int


class HandoverPackage(TypedDict, total=False):
    id: str
    project_id: str
    label: str
    includes_takeoff_id: str
    status: str
    transmitted_at: Optional[str]
    fm_decision_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
