"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    INCIDENT_COMMANDER = "IncidentCommander"
    SHELTER_COORDINATOR = "ShelterCoordinator"
    TRAFFIC_MANAGER = "TrafficManager"
    REGISTRAR = "Registrar"
    PUBLIC_INFO_OFFICER = "PublicInfoOfficer"


class IncidentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ALL_CLEAR = "ALL_CLEAR"
    STOOD_DOWN = "STOOD_DOWN"


class HazardType(str, Enum):
    WILDFIRE = "WILDFIRE"
    FLOOD = "FLOOD"
    HURRICANE = "HURRICANE"
    HAZMAT = "HAZMAT"
    TSUNAMI = "TSUNAMI"


class ZoneOrderLevel(str, Enum):
    NONE = "NONE"
    VOLUNTARY = "VOLUNTARY"
    MANDATORY = "MANDATORY"
    RE_ENTRY_ALLOWED = "RE_ENTRY_ALLOWED"


class ShelterStatus(str, Enum):
    STANDBY = "STANDBY"
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"


class StaffShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CONGESTED = "CONGESTED"
    CLOSED = "CLOSED"


class ContraflowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ContraflowDirection(str, Enum):
    INBOUND_REVERSED = "INBOUND_REVERSED"
    OUTBOUND = "OUTBOUND"


class RegistrantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ADVISED = "ADVISED"
    ORDERED = "ORDERED"
    SHELTERED = "SHELTERED"
    CLEARED_FOR_REENTRY = "CLEARED_FOR_REENTRY"


class FunctionalNeeds(str, Enum):
    NONE = "NONE"
    MOBILITY = "MOBILITY"
    MEDICAL_ELECTRICITY = "MEDICAL_ELECTRICITY"
    OXYGEN = "OXYGEN"
    COGNITIVE = "COGNITIVE"


class AssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class CredentialType(str, Enum):
    RESIDENT = "RESIDENT"
    ESSENTIAL_WORKER = "ESSENTIAL_WORKER"
    UTILITY = "UTILITY"


class CredentialStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AlertSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    WATCH = "WATCH"
    WARNING = "WARNING"
    EXTREME = "EXTREME"


class AlertChannel(str, Enum):
    WEA = "WEA"
    EAS = "EAS"
    IPAWS = "IPAWS"
    SMS = "SMS"


class ChannelStatus(str, Enum):
    NA = "NA"
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


class AlertOverallStatus(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    SENT = "SENT"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# All entities carry common fields (id, created_at, updated_at, version).

class Incident(TypedDict, total=False):
    id: str
    name: str
    jurisdiction: str
    hazard_type: str
    status: str
    ipaws_daily_slot_budget: int
    ipaws_slots_reserved: int
    activated_at: Optional[str]
    all_clear_at: Optional[str]
    clearance_estimate_minutes: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict, total=False):
    id: str
    incident_id: str
    name: str
    geofence_wkt: str
    residential_population: int
    transient_population: int
    daytime_occupancy_factor: float
    nighttime_occupancy_factor: float
    order_level: str
    population_at_risk: int
    order_issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shelter(TypedDict, total=False):
    id: str
    incident_id: str
    name: str
    physical_capacity: int
    ada_reserved_pct: float
    power_backup: bool
    status: str
    staffed_capacity_now: int
    effective_capacity: int
    reserved_beds: int
    occupied_beds: int
    provisional_available: int
    confirmed_available: int
    created_at: str
    updated_at: str
    version: int


class StaffShift(TypedDict, total=False):
    id: str
    shelter_id: str
    role_label: str
    staffed_beds: int
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EvacuationRoute(TypedDict, total=False):
    id: str
    incident_id: str
    name: str
    corridor_label: str
    throughput_vph: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContraflowSegment(TypedDict, total=False):
    id: str
    route_id: str
    segment_key: str
    direction: str
    window_start_utc: str
    window_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Registrant(TypedDict, total=False):
    id: str
    zone_id: str
    household_name: str
    party_size: int
    functional_needs: str
    transport_required: bool
    status: str
    current_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShelterAssignment(TypedDict, total=False):
    id: str
    registrant_id: str
    shelter_id: str
    party_size: int
    status: str
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessCredential(TypedDict, total=False):
    id: str
    zone_id: str
    registrant_id: str
    credential_type: str
    valid_from_utc: str
    valid_until_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AlertDispatch(TypedDict, total=False):
    id: str
    zone_id: str
    message: str
    severity: str
    channels: List[str]
    wea_status: str
    eas_status: str
    ipaws_status: str
    sms_status: str
    overall_status: str
    created_at: str
    updated_at: str
    version: int
