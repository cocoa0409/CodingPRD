"""Domain types: entity TypedDicts, status enums, role enum for the CAD/911 dispatch API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    CALLTAKER = "Calltaker"
    DISPATCHER = "Dispatcher"
    FIELD_UNIT = "FieldUnit"
    SUPERVISOR = "Supervisor"
    RECORDS = "Records"
    SYSTEM_CLOCK = "SystemClock"


# --- Enums ---
class AgencyDiscipline(str, Enum):
    POLICE = "POLICE"
    FIRE = "FIRE"
    EMS = "EMS"


class AgencyStatus(str, Enum):
    ONLINE = "ONLINE"
    MUTUAL_AID_ONLY = "MUTUAL_AID_ONLY"
    OFFLINE = "OFFLINE"


class UnitCapability(str, Enum):
    PATROL = "PATROL"
    K9 = "K9"
    SUPERVISOR_UNIT = "SUPERVISOR_UNIT"
    ENGINE = "ENGINE"
    LADDER = "LADDER"
    MEDIC_ALS = "MEDIC_ALS"
    MEDIC_BLS = "MEDIC_BLS"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DISPATCHED = "DISPATCHED"
    ENROUTE = "ENROUTE"
    ONSCENE = "ONSCENE"
    CLEARING = "CLEARING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class HazardClass(str, Enum):
    WEAPONS = "WEAPONS"
    HAZMAT = "HAZMAT"
    COMBATIVE_SUBJECT = "COMBATIVE_SUBJECT"
    STRUCTURAL = "STRUCTURAL"
    MEDICAL_HISTORY = "MEDICAL_HISTORY"
    NONE = "NONE"


class IncidentType(str, Enum):
    STRUCTURE_FIRE = "STRUCTURE_FIRE"
    MEDICAL_EMERGENCY = "MEDICAL_EMERGENCY"
    TRAFFIC_COLLISION = "TRAFFIC_COLLISION"
    ASSAULT_IN_PROGRESS = "ASSAULT_IN_PROGRESS"
    ALARM = "ALARM"
    WELFARE_CHECK = "WELFARE_CHECK"


class AliConfidence(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"
    UNKNOWN = "UNKNOWN"


class IncidentLifecycleStatus(str, Enum):
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    ACTIVE = "ACTIVE"
    HELD = "HELD"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    ENROUTE = "ENROUTE"
    ONSCENE = "ONSCENE"
    CLEARED = "CLEARED"
    CANCELLED = "CANCELLED"


class DispositionCode(str, Enum):
    REPORT_TAKEN = "REPORT_TAKEN"
    ARREST = "ARREST"
    TRANSPORT = "TRANSPORT"
    FIRE_OUT = "FIRE_OUT"
    UNFOUNDED = "UNFOUNDED"
    GONE_ON_ARRIVAL = "GONE_ON_ARRIVAL"
    CANCELLED = "CANCELLED"


class ReportStandard(str, Enum):
    NENA = "NENA"
    NFIRS = "NFIRS"


# --- Entities (common_fields: true → id, created_at, updated_at, version) ---
class Agency(TypedDict):
    id: str
    name: str
    discipline: str
    response_sla_seconds: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    agency_id: str
    name: str
    grid_x: int
    grid_y: int
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    agency_id: str
    station_id: str
    call_sign: str
    capability: str
    status: str
    grid_x: int
    grid_y: int
    active_incident_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PremiseAlert(TypedDict):
    id: str
    grid_x: int
    grid_y: int
    hazard_class: str
    min_priority_floor: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    incident_number: str
    ani: str
    ali_grid_x: int
    ali_grid_y: int
    ali_confidence: str
    incident_type: str
    priority_level: int
    base_priority_level: int
    required_disciplines: List[str]
    lifecycle_status: str
    premise_alert_id: Optional[str]
    received_at: str
    first_dispatch_at: Optional[str]
    first_onscene_at: Optional[str]
    closed_at: Optional[str]
    escalation_count: int
    disposition_code: Optional[str]
    response_time_seconds: Optional[int]
    total_handle_seconds: Optional[int]
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    incident_id: str
    unit_id: str
    recommended: bool
    travel_distance: int
    status: str
    dispatched_at: str
    enroute_at: Optional[str]
    onscene_at: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Disposition(TypedDict):
    id: str
    incident_id: str
    disposition_code: str
    narrative: str
    requires_nfirs: bool
    created_at: str
    updated_at: str
    version: int


# CfsReport — common_fields: false → immutable append-only: id + created_at ONLY
class CfsReport(TypedDict):
    id: str
    incident_id: str
    report_standard: str
    response_time_seconds: Optional[int]
    total_handle_seconds: Optional[int]
    sla_breached: bool
    unit_count: int
    disposition_code: Optional[str]
    created_at: str
