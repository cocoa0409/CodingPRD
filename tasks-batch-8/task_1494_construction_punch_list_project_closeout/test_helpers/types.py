"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    GC_PROJECT_MANAGER = "GCProjectManager"
    GC_INSPECTOR = "GCInspector"
    OWNER_REP = "OwnerRep"
    SUBCONTRACTOR_REP = "SubcontractorRep"


class ProjectStatus(str, Enum):
    MOBILIZED = "MOBILIZED"
    PUNCH_ACTIVE = "PUNCH_ACTIVE"
    SC_REVIEW = "SC_REVIEW"
    SUBSTANTIALLY_COMPLETE = "SUBSTANTIALLY_COMPLETE"
    CLOSEOUT_IN_PROGRESS = "CLOSEOUT_IN_PROGRESS"
    FINAL_RELEASE_PENDING = "FINAL_RELEASE_PENDING"
    CLOSED = "CLOSED"


class TradeName(str, Enum):
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    HVAC = "HVAC"
    DRYWALL = "DRYWALL"
    FLOORING = "FLOORING"
    ROOFING = "ROOFING"
    PAINTING = "PAINTING"
    CONCRETE = "CONCRETE"


class ResponsibleType(str, Enum):
    SUBCONTRACTOR = "SUBCONTRACTOR"
    SELF_PERFORMED = "SELF_PERFORMED"


class LienWaiverStatus(str, Enum):
    NONE = "NONE"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LienWaiverType(str, Enum):
    CONDITIONAL = "CONDITIONAL"
    UNCONDITIONAL = "UNCONDITIONAL"


class PunchWalkStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class PunchItemStatus(str, Enum):
    OPEN = "OPEN"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class PunchItemSeverity(str, Enum):
    LIFE_SAFETY = "LIFE_SAFETY"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class DocType(str, Enum):
    OM_MANUAL = "OM_MANUAL"
    WARRANTY_DOC = "WARRANTY_DOC"
    AS_BUILT = "AS_BUILT"


class DocStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TrainingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"


class ReleaseKind(str, Enum):
    REDUCTION = "REDUCTION"
    FINAL = "FINAL"


class ReleaseStatus(str, Enum):
    REQUESTED = "REQUESTED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class WarrantyCaseStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"


class WarrantySeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class Project(TypedDict, total=False):
    id: str
    name: str
    contract_value_cents: int
    retainage_pct: float
    reduction_policy: str
    warranty_sla_mode: str
    status: str
    open_life_safety_count: int
    open_major_count: int
    open_minor_count: int
    sc_eligible: bool
    substantial_completion_date: Optional[str]
    warranty_start_date: Optional[str]
    beneficial_occupancy_registered: bool
    beneficial_occupancy_date: Optional[str]
    retainage_held_cents: int
    retainage_paid_cents: int
    retainage_outstanding_cents: int
    sc_rejection_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TradePackage(TypedDict, total=False):
    id: str
    project_id: str
    trade_name: str
    responsible_type: str
    subcontractor_org: Optional[str]
    has_completed_walk: bool
    open_item_count: int
    om_doc_approved: bool
    warranty_doc_approved: bool
    asbuilt_doc_approved: bool
    has_conducted_training: bool
    lien_waiver_status: str
    lien_waiver_type: Optional[str]
    lien_waiver_amount_cents: Optional[int]
    lien_waiver_file_ref: Optional[str]
    closeout_ready: bool
    created_at: str
    updated_at: str
    version: int


class PunchWalk(TypedDict, total=False):
    id: str
    project_id: str
    trade_package_id: str
    lead_inspector_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PunchItem(TypedDict, total=False):
    id: str
    project_id: str
    trade_package_id: str
    punch_walk_id: Optional[str]
    title: str
    severity: str
    location_building: str
    location_floor: str
    location_area: str
    photo_ref: str
    status: str
    ready_by_user_id: Optional[str]
    ready_at: Optional[str]
    verified_by_user_id: Optional[str]
    rejection_count: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CloseoutDocument(TypedDict, total=False):
    id: str
    project_id: str
    trade_package_id: str
    doc_type: str
    file_ref: str
    revision: int
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict, total=False):
    id: str
    project_id: str
    trade_package_id: str
    system_name: str
    location_room: str
    scheduled_start: str
    scheduled_end: str
    reschedule_count: int
    attendee_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RetainageRelease(TypedDict, total=False):
    id: str
    project_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyCase(TypedDict, total=False):
    id: str
    project_id: str
    title: str
    severity: str
    description: str
    reported_at: str
    sla_due_at: Optional[str]
    resolution_note: Optional[str]
    denial_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
