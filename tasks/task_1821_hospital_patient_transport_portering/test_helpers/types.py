"""Domain types: entity TypedDicts, status enums, role enum (PRD §2 and §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    REQUESTING_CLINICIAN = "RequestingClinician"
    TRANSPORT_DISPATCHER = "TransportDispatcher"
    TRANSPORTER = "Transporter"
    HOUSEKEEPING_STAFF = "HousekeepingStaff"
    TRANSPORT_SUPERVISOR = "TransportSupervisor"


class LocationType(str, Enum):
    WARD = "WARD"
    ICU = "ICU"
    ED = "ED"
    OR = "OR"
    IMAGING = "IMAGING"
    DISCHARGE_LOUNGE = "DISCHARGE_LOUNGE"
    OTHER = "OTHER"


class TransporterStatus(str, Enum):
    OFF_SHIFT = "OFF_SHIFT"
    ON_SHIFT = "ON_SHIFT"
    SUSPENDED = "SUSPENDED"


class EquipmentType(str, Enum):
    WHEELCHAIR = "WHEELCHAIR"
    STRETCHER = "STRETCHER"
    BARIATRIC_STRETCHER = "BARIATRIC_STRETCHER"


class EquipmentStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    AWAITING_CLEANING = "AWAITING_CLEANING"
    IN_CLEANING = "IN_CLEANING"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RequestPriority(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    STAT = "STAT"


class RequiredEquipment(str, Enum):
    PORTER_ONLY = "PORTER_ONLY"
    WHEELCHAIR = "WHEELCHAIR"
    STRETCHER = "STRETCHER"
    BARIATRIC_STRETCHER = "BARIATRIC_STRETCHER"


class IsolationPrecaution(str, Enum):
    NONE = "NONE"
    CONTACT = "CONTACT"
    DROPLET = "DROPLET"
    AIRBORNE = "AIRBORNE"


class RequestStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    AT_PICKUP = "AT_PICKUP"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class SlaPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class CleaningTaskType(str, Enum):
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class CleaningTaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    VERIFIED = "VERIFIED"


class ShiftStatus(str, Enum):
    PLANNED = "PLANNED"
    CANCELLED = "CANCELLED"


class DayType(str, Enum):
    WEEKDAY = "WEEKDAY"
    WEEKEND = "WEEKEND"


class DelayRecordKind(str, Enum):
    SLA_BREACH = "SLA_BREACH"
    APPOINTMENT_LATE = "APPOINTMENT_LATE"


class DelayCauseCode(str, Enum):
    NO_TRANSPORTER = "NO_TRANSPORTER"
    NO_EQUIPMENT = "NO_EQUIPMENT"
    CLEANING_BACKLOG = "CLEANING_BACKLOG"
    PATIENT_NOT_READY = "PATIENT_NOT_READY"
    SYSTEM = "SYSTEM"
    OTHER = "OTHER"


class DelayRecordedVia(str, Enum):
    SWEEP = "SWEEP"
    COMPLETION = "COMPLETION"


class Location(TypedDict):
    id: str
    code: str
    name: str
    location_type: str
    zone_code: str
    created_at: str
    updated_at: str
    version: int


class TravelEdge(TypedDict):
    id: str
    from_location_id: str
    to_location_id: str
    base_minutes: int
    airborne_minutes: int
    created_at: str
    updated_at: str
    version: int


class Transporter(TypedDict):
    id: str
    name: str
    home_location_id: str
    certified_equipment: List[str]
    oxygen_certified: bool
    isolation_certified: bool
    status: str
    current_location_id: str
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict):
    id: str
    asset_tag: str
    equipment_type: str
    status: str
    current_location_id: str
    isolation_contaminated: bool
    created_at: str
    updated_at: str
    version: int


class TransportRequest(TypedDict):
    id: str
    patient_ref: str
    origin_location_id: str
    destination_location_id: str
    priority: str
    required_equipment: str
    oxygen_required: bool
    isolation_precaution: str
    scheduled_pickup_time: Optional[str]
    appointment_deadline: Optional[str]
    requested_by: str
    status: str
    sla_posture: str
    escalation_count: int
    decline_count: int
    release_count: int
    offer_seq_count: int
    excluded_transporter_ids: List[str]
    assigned_transporter_id: Optional[str]
    assigned_equipment_id: Optional[str]
    duplicate_of_id: Optional[str]
    committed_eta_minutes: Optional[int]
    response_minutes: Optional[int]
    at_pickup_at: Optional[str]
    picked_up_at: Optional[str]
    completed_at: Optional[str]
    closed_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DispatchOffer(TypedDict):
    id: str
    transport_request_id: str
    transporter_id: str
    status: str
    offer_seq: int
    estimated_travel_minutes: int
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CleaningTask(TypedDict):
    id: str
    equipment_asset_id: str
    transport_request_id: str
    task_type: str
    status: str
    started_at: Optional[str]
    finished_at: Optional[str]
    verified_at: Optional[str]
    performed_by: Optional[str]
    verified_by: Optional[str]
    rework_count: int
    created_at: str
    updated_at: str
    version: int


class StaffingShift(TypedDict):
    id: str
    transporter_id: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DemandCurve(TypedDict):
    id: str
    day_type: str
    hour_block: int
    priority: str
    expected_requests: float
    mean_service_minutes: int
    created_at: str
    updated_at: str
    version: int


# DelayRecord is a deliberately lighter resource: it carries only id and
# created_at as system fields — updated_at and version are absent (PRD §2.4).
class DelayRecord(TypedDict):
    id: str
    transport_request_id: str
    record_kind: str
    delay_minutes: int
    impact_minutes: int
    cause_code: str
    recorded_via: str
    created_at: str
