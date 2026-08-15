"""Domain types: entity TypedDicts, status enums, role enum for the EVS API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    EVS_ADMINISTRATOR = "EVSAdministrator"
    EVS_DISPATCHER = "EVSDispatcher"
    EVS_TECHNICIAN = "EVSTechnician"
    QUALITY_AUDITOR = "QualityAuditor"
    BED_PLACEMENT_COORDINATOR = "BedPlacementCoordinator"
    INFECTION_PREVENTIONIST = "InfectionPreventionist"
    ANY = "Any"


class OutbreakPosture(str, Enum):
    NORMAL = "NORMAL"
    OUTBREAK = "OUTBREAK"


class BedKind(str, Enum):
    STANDARD = "STANDARD"
    ISOLATION = "ISOLATION"
    ICU = "ICU"


class BedStatus(str, Enum):
    VACANT_DIRTY = "VACANT_DIRTY"
    CLEAN_IN_PROGRESS = "CLEAN_IN_PROGRESS"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    READY = "READY"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DemandStatus(str, Enum):
    OPEN = "OPEN"
    MATCHED = "MATCHED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class UrgencyTier(str, Enum):
    STAT = "STAT"
    URGENT = "URGENT"
    STANDARD = "STANDARD"


class CleanType(str, Enum):
    ROUTINE = "ROUTINE"
    ISOLATION = "ISOLATION"
    TERMINAL = "TERMINAL"


class CleanRequestStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_QA = "PENDING_QA"
    NEEDS_RECLEAN = "NEEDS_RECLEAN"
    VERIFIED = "VERIFIED"
    CANCELLED = "CANCELLED"


class ShiftStatus(str, Enum):
    OFF_SHIFT = "OFF_SHIFT"
    ON_SHIFT = "ON_SHIFT"
    ON_BREAK = "ON_BREAK"


class Capability(str, Enum):
    CLEAN = "CLEAN"
    AUDIT = "AUDIT"


class Certification(str, Enum):
    ISO_CERT = "ISO_CERT"
    TERMINAL_CERT = "TERMINAL_CERT"


class AuditMethod(str, Enum):
    ATP_SWAB = "ATP_SWAB"
    FLUORESCENT_MARKER = "FLUORESCENT_MARKER"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class AuditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VOIDED = "VOIDED"


class SupplyItemCode(str, Enum):
    DISINFECTANT = "DISINFECTANT"
    PPE_PACK = "PPE_PACK"
    CLOTH = "CLOTH"
    SEALANT = "SEALANT"


class StockStatus(str, Enum):
    LOW = "LOW"
    STOCKED = "STOCKED"


class LedgerEntryType(str, Enum):
    RESTOCK = "RESTOCK"
    CONSUME = "CONSUME"
    RECOUNT_ADJUSTMENT = "RECOUNT_ADJUSTMENT"


class PathogenClass(str, Enum):
    C_DIFF = "C_DIFF"
    MRSA = "MRSA"
    NOROVIRUS = "NOROVIRUS"
    OTHER = "OTHER"


class OutbreakStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"
    CANCELLED = "CANCELLED"


class NotificationStatus(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RETRACTED = "RETRACTED"
    EXPIRED = "EXPIRED"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version (PRD §2.5).
# SupplyLedgerEntry and TurnaroundSnapshot are append-only: id + created_at only.


class Unit(TypedDict, total=False):
    id: str
    unit_code: str
    display_name: str
    outbreak_posture: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Bed(TypedDict, total=False):
    id: str
    unit_id: str
    bed_code: str
    bed_kind: str
    bed_status: str
    last_discharge_at: Optional[str]
    last_ready_at: Optional[str]
    tat_total_minutes: Optional[int]
    tat_clean_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PlacementDemand(TypedDict, total=False):
    id: str
    unit_id: str
    required_bed_kind: str
    urgency_tier: str
    needed_by: str
    status: str
    priority_score: float
    matched_bed_id: Optional[str]
    fulfilled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CleanRequest(TypedDict, total=False):
    id: str
    bed_id: str
    unit_id: str
    clean_type: str
    status: str
    priority_tier: str
    priority_score: float
    sla_target_minutes: int
    sla_due_at: str
    sla_breached: bool
    current_estimate_minutes: int
    pinned_base_minutes: int
    pinned_outbreak_multiplier_bps: int
    pinned_with_outbreak: bool
    assigned_staff_id: Optional[str]
    last_completed_by_staff_id: Optional[str]
    reclean_count: int
    planned_start_at: Optional[str]
    planned_end_at: Optional[str]
    first_started_at: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]
    verified_at: Optional[str]
    supply_reserved: bool
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict, total=False):
    id: str
    employee_code: str
    display_name: str
    capabilities: List[str]
    certifications: List[str]
    shift_status: str
    active_clean_count: int
    completed_clean_count: int
    verified_credit_total: float
    qa_fail_count: int
    shift_seconds_today: int
    productivity_score: float
    stat_eligible: bool
    last_clock_in_at: Optional[str]
    break_started_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityAudit(TypedDict, total=False):
    id: str
    clean_request_id: str
    auditor_id: str
    audit_method: str
    rlu_reading: Optional[int]
    marker_fraction_removed: Optional[float]
    result: str
    threshold_used: float
    audit_status: str
    created_ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class SupplyItem(TypedDict, total=False):
    id: str
    item_code: str
    display_name: str
    on_hand_quantity: int
    reserved_quantity: int
    reorder_threshold: int
    stock_status: str
    created_at: str
    updated_at: str
    version: int


class SupplyLedgerEntry(TypedDict, total=False):
    # Append-only: id + created_at only; NO updated_at, NO version (PRD §2.5).
    id: str
    supply_item_id: str
    clean_request_id: Optional[str]
    entry_type: str
    quantity_delta: int
    note: Optional[str]
    created_at: str


class OutbreakEvent(TypedDict, total=False):
    id: str
    unit_id: str
    pathogen_class: str
    declared_reason: Optional[str]
    status: str
    activated_at: Optional[str]
    lifted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BedReadyNotification(TypedDict, total=False):
    id: str
    bed_id: str
    demand_id: str
    status: str
    sent_at: str
    acknowledged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    bed_id: str
    start_at: str
    end_at: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CleanStandard(TypedDict, total=False):
    id: str
    clean_type: str
    base_minutes: int
    outbreak_multiplier_bps: int
    atp_rlu_threshold: int
    created_at: str
    updated_at: str
    version: int


class TurnaroundSnapshot(TypedDict, total=False):
    # Append-only: id + created_at only; NO updated_at, NO version (PRD §2.5).
    id: str
    unit_id: str
    ops_run_index: int
    window_start: str
    window_end: str
    verified_count: int
    sla_breach_count: int
    tat_total_p50_minutes: Optional[float]
    tat_total_p90_minutes: Optional[float]
    tat_clean_p50_minutes: Optional[float]
    tat_clean_p90_minutes: Optional[float]
    created_at: str
