"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums (PRD §3 narratives)
# ---------------------------------------------------------------------------
class TrayStatus(str, Enum):
    AWAITING_DECONTAMINATION = "AWAITING_DECONTAMINATION"
    IN_DECONTAMINATION = "IN_DECONTAMINATION"
    DECONTAMINATED = "DECONTAMINATED"
    IN_ASSEMBLY = "IN_ASSEMBLY"
    ASSEMBLED = "ASSEMBLED"
    IN_LOAD = "IN_LOAD"
    STERILE = "STERILE"
    IN_USE = "IN_USE"
    QUARANTINED = "QUARANTINED"
    DISCARDED = "DISCARDED"


class InstrumentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    FLAGGED_FOR_REPAIR = "FLAGGED_FOR_REPAIR"
    OUT_FOR_REPAIR = "OUT_FOR_REPAIR"
    RETIRED = "RETIRED"


class RepairOrderStatus(str, Enum):
    OPEN = "OPEN"
    SENT = "SENT"
    CLOSED_FIXED = "CLOSED_FIXED"
    CLOSED_CONDEMNED = "CLOSED_CONDEMNED"


class SterilizerStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"


class LoadStatus(str, Enum):
    LOADING = "LOADING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"
    FAILED_CYCLE = "FAILED_CYCLE"
    FAILED_BI = "FAILED_BI"
    RECALLED = "RECALLED"
    ABORTED = "ABORTED"


class BiStatus(str, Enum):
    INCUBATING = "INCUBATING"
    RESULT_RECORDED = "RESULT_RECORDED"


class BiResult(str, Enum):
    PENDING = "PENDING"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"


class CaseStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    TRAYS_RESERVED = "TRAYS_RESERVED"
    AT_RISK = "AT_RISK"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    USED = "USED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class IussStatus(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    REVIEWED = "REVIEWED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CERTIFICATION_EXPIRED = "CERTIFICATION_EXPIRED"


class LoanerStatus(str, Enum):
    BOOKED = "BOOKED"
    RECEIVED = "RECEIVED"
    LATE_RECEIVED = "LATE_RECEIVED"
    READY = "READY"
    IN_USE = "IN_USE"
    RETURNED = "RETURNED"


class VerificationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PackagingType(str, Enum):
    WRAPPED = "WRAPPED"
    RIGID_CONTAINER = "RIGID_CONTAINER"


class SterilizerMethod(str, Enum):
    STEAM_GRAVITY = "STEAM_GRAVITY"
    STEAM_PREVAC = "STEAM_PREVAC"
    LOW_TEMP_H2O2 = "LOW_TEMP_H2O2"


class Criticality(str, Enum):
    ROUTINE = "ROUTINE"
    CRITICAL = "CRITICAL"


class CasePriority(str, Enum):
    ELECTIVE = "ELECTIVE"
    URGENT = "URGENT"
    EMERGENCY = "EMERGENCY"


class RepairOutcome(str, Enum):
    FIXED = "FIXED"
    CONDEMNED = "CONDEMNED"


class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    SPD_TECHNICIAN = "SpdTechnician"
    SPD_SUPERVISOR = "SpdSupervisor"
    OR_SCHEDULER = "OrScheduler"
    QUALITY_AUDITOR = "QualityAuditor"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
class InstrumentRequirementLine(TypedDict):
    instrument_type: str
    quantity: int


class TrayTemplate(TypedDict):
    id: str
    code: str
    name: str
    specialty: str
    packaging_type: str
    instrument_requirements: List[InstrumentRequirementLine]
    assembly_minutes: int
    created_at: str
    updated_at: str
    version: int


class Tray(TypedDict):
    id: str
    template_id: str
    label: str
    status: str
    current_load_id: Optional[str]
    sterility_expires_at: Optional[str]
    cycles_completed: int
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssemblyVerificationLine(TypedDict):
    instrument_type: str
    counted_qty: int


# Immutable audit record (PRD §2.5): carries ONLY id + created_at — no
# updated_at, no version.
class AssemblyVerification(TypedDict):
    id: str
    tray_id: str
    technician_id: str
    lines: List[AssemblyVerificationLine]
    result: str
    mismatch_count: int
    created_at: str


class Instrument(TypedDict):
    id: str
    instrument_type: str
    serial_number: str
    max_cycles: int
    usage_cycles: int
    replacement_cost_cents: int
    criticality: str
    status: str
    repair_count: int
    assigned_tray_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    instrument_id: str
    status: str
    vendor: str
    quoted_cost_cents: int
    actual_cost_cents: int
    recommended_outcome: str
    outcome: Optional[str]
    outcome_overridden: bool
    created_at: str
    updated_at: str
    version: int


class Sterilizer(TypedDict):
    id: str
    name: str
    method: str
    chamber_capacity: int
    cycle_minutes: int
    required_certification_level: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SterilizationLoad(TypedDict):
    id: str
    sterilizer_id: str
    operator_id: str
    planned_start_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    released_at: Optional[str]
    status: str
    tray_count: int
    total_chargeback_cents: Optional[int]
    recall_reason: Optional[str]
    recalled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BiologicalIndicator(TypedDict):
    id: str
    load_id: str
    lot_number: str
    status: str
    result: str
    due_at: str
    recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ORCase(TypedDict):
    id: str
    case_number: str
    surgeon: str
    scheduled_start_at: str
    scheduled_end_at: str
    priority: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrayReservation(TypedDict):
    id: str
    case_id: str
    tray_id: str
    status: str
    reserved_at: str
    created_at: str
    updated_at: str
    version: int


class IussException(TypedDict):
    id: str
    tray_id: str
    case_id: str
    justification: str
    logged_by_id: str
    logged_at: str
    status: str
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    name: str
    certification_level: int
    certified_methods: List[str]
    certification_expires_at: str
    status: str
    competency_score: float
    competency_score_lifetime: float
    created_at: str
    updated_at: str
    version: int


class LoanerSet(TypedDict):
    id: str
    vendor: str
    case_id: str
    tray_count: int
    due_by: str
    received_at: Optional[str]
    received_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int
