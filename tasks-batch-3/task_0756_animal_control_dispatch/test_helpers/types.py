"""Domain types: entity TypedDicts, status enums, role enum.

All names use the terminology from the Animal-Control Dispatch PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    FIELD_OFFICER = "FieldOfficer"
    SUPERVISOR = "Supervisor"
    HEALTH_DEPT_LIAISON = "HealthDeptLiaison"


# --------------------------------------------------------------------------
# Status enums (one per stateful entity)
# --------------------------------------------------------------------------
class ComplaintStatus(str, Enum):
    NEW = "NEW"
    DISPATCHED = "DISPATCHED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class DispatchStatus(str, Enum):
    PENDING = "PENDING"
    EN_ROUTE = "EN_ROUTE"
    CLEARED = "CLEARED"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"
    CLOSED = "CLOSED"


class QuarantineHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class ImpoundStatus(str, Enum):
    HELD = "HELD"
    REDEEMED = "REDEEMED"
    ADOPTED = "ADOPTED"
    EUTHANIZED = "EUTHANIZED"
    RELEASED = "RELEASED"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    COURT_REFERRED = "COURT_REFERRED"


class RabiesReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"


# --------------------------------------------------------------------------
# Value enums (inputs)
# --------------------------------------------------------------------------
class Zone(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"
    CENTRAL = "CENTRAL"


class AnimalType(str, Enum):
    DOG = "DOG"
    CAT = "CAT"
    WILDLIFE = "WILDLIFE"
    LIVESTOCK = "LIVESTOCK"
    OTHER = "OTHER"


class ComplaintType(str, Enum):
    STRAY = "STRAY"
    BITE = "BITE"
    CRUELTY = "CRUELTY"
    DANGEROUS_DOG = "DANGEROUS_DOG"
    NOISE = "NOISE"
    OTHER = "OTHER"


class Priority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class CaseType(str, Enum):
    STRAY = "STRAY"
    BITE = "BITE"
    CRUELTY = "CRUELTY"
    DANGEROUS_DOG = "DANGEROUS_DOG"


class FieldOutcome(str, Enum):
    RESOLVED_ON_SCENE = "RESOLVED_ON_SCENE"
    ANIMAL_IMPOUNDED = "ANIMAL_IMPOUNDED"
    CASE_OPENED = "CASE_OPENED"
    GONE_ON_ARRIVAL = "GONE_ON_ARRIVAL"
    REFERRED = "REFERRED"


class HoldType(str, Enum):
    HOME_QUARANTINE = "HOME_QUARANTINE"
    FACILITY_QUARANTINE = "FACILITY_QUARANTINE"


class Disposition(str, Enum):
    REDEEMED = "REDEEMED"
    ADOPTED = "ADOPTED"
    RELEASED = "RELEASED"
    EUTHANIZED = "EUTHANIZED"


class ViolationCode(str, Enum):
    UNLICENSED = "UNLICENSED"
    LEASH = "LEASH"
    DANGEROUS = "DANGEROUS"
    BITE = "BITE"
    CRUELTY = "CRUELTY"


class NoteType(str, Enum):
    OBSERVATION = "OBSERVATION"
    EVIDENCE = "EVIDENCE"
    WITNESS = "WITNESS"
    FOLLOWUP = "FOLLOWUP"


class Resolution(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    UNFOUNDED = "UNFOUNDED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id, created_at, updated_at, version
# common_fields: false -> id, created_at only
# --------------------------------------------------------------------------
class Complaint(TypedDict):
    id: str
    reporter_name: str
    reporter_phone: str
    zone: str
    animal_type: str
    complaint_type: str
    involves_vulnerable_victim: bool
    description: Optional[str]
    severity_score: float
    priority: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Officer(TypedDict):
    id: str
    name: str
    badge_number: str
    territory_zone: str
    shift_start_at: str
    shift_end_at: str
    max_daily_dispatches: int
    active_dispatch_count: int
    created_at: str
    updated_at: str
    version: int


class Kennel(TypedDict):
    id: str
    code: str
    facility_zone: str
    occupied_slots: int
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    complaint_id: str
    officer_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    eta_minutes: Optional[int]
    field_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict):
    id: str
    complaint_id: str
    assigned_officer_id: str
    case_type: str
    animal_identifier: Optional[str]
    risk_score: float
    outstanding_fines_total: float
    public_health_flag: bool
    substantiated_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvestigationNote(TypedDict):
    # common_fields: false — append-only, immutable: id + created_at only.
    id: str
    case_id: str
    note_type: str
    body: str
    author_role: str
    author_id: str
    created_at: str


class QuarantineHold(TypedDict):
    id: str
    case_id: str
    animal_identifier: Optional[str]
    hold_type: str
    start_at: str
    required_days: int
    release_due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Impound(TypedDict):
    id: str
    case_id: str
    kennel_id: str
    animal_identifier: Optional[str]
    licensed: bool
    impounded_at: str
    hold_until: str
    boarding_fee: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    case_id: str
    violation_code: str
    issued_to_name: str
    issued_to_ref: str
    base_fine: float
    fine_amount: float
    issued_at: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RabiesReport(TypedDict):
    id: str
    case_id: str
    quarantine_hold_id: str
    animal_identifier: Optional[str]
    victim_name: str
    exposure_date: str
    deadline_at: str
    submitted_at: str
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int
