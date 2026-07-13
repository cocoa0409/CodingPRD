"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    BEACH_CAPTAIN = "BeachCaptain"
    LIFEGUARD = "Lifeguard"
    WATER_QUALITY_INSPECTOR = "WaterQualityInspector"
    PARKING_CLERK = "ParkingClerk"
    PUBLIC = "Public"


class FlagStatus(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    RED = "RED"
    BLACK = "BLACK"


class WaterStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RipCurrentLevel(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class TowerStatus(str, Enum):
    OPEN = "OPEN"
    OFFLINE = "OFFLINE"


class CertificationLevel(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    CAPTAIN = "CAPTAIN"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_DUTY = "ON_DUTY"
    ON_BREAK = "ON_BREAK"
    OFF_DUTY = "OFF_DUTY"
    CANCELLED = "CANCELLED"


class IncidentType(str, Enum):
    RESCUE = "RESCUE"
    MEDICAL = "MEDICAL"
    LOST_CHILD = "LOST_CHILD"
    FIRST_AID = "FIRST_AID"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_ON_SCENE = "RESOLVED_ON_SCENE"
    ESCALATED_EMS = "ESCALATED_EMS"
    REUNITED = "REUNITED"
    CLOSED = "CLOSED"


class AdvisoryBasis(str, Enum):
    SINGLE_SAMPLE = "SINGLE_SAMPLE"
    GEOMEAN_30DAY = "GEOMEAN_30DAY"


class AdvisoryLevel(str, Enum):
    NONE = "NONE"
    ADVISORY = "ADVISORY"
    CLOSURE = "CLOSURE"


class AdvisoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    LIFTED = "LIFTED"


class VehicleType(str, Enum):
    CAR = "CAR"
    OVERSIZED = "OVERSIZED"


class PassType(str, Enum):
    DAILY = "DAILY"
    SEASON = "SEASON"


class ParkingPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


# --- Entities with common_fields: true (id, created_at, updated_at, version) ---

class Beach(TypedDict):
    id: str
    name: str
    town_code: str
    season_start_date: str
    season_end_date: str
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict):
    id: str
    beach_id: str
    name: str
    min_guards_required: int
    flag_status: str
    water_status: str
    rip_current_level: str
    on_duty_guard_count: int
    weather_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tower(TypedDict):
    id: str
    zone_id: str
    label: str
    max_concurrent_guards: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lifeguard(TypedDict):
    id: str
    beach_id: str
    name: str
    certification_level: str
    employee_ref: str
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    lifeguard_id: str
    tower_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    clock_in_at: Optional[str]
    clock_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    zone_id: str
    lifeguard_id: Optional[str]
    type: str
    severity: str
    occurred_at: str
    victim_count: int
    description: str
    status: str
    ems_transported: Optional[bool]
    ems_hospital: Optional[str]
    ems_unit: Optional[str]
    ems_narrative: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Advisory(TypedDict):
    id: str
    zone_id: str
    basis: str
    level: str
    assessed_value: float
    status: str
    reason: Optional[str]
    issued_at: str
    created_at: str
    updated_at: str
    version: int


class ParkingLot(TypedDict):
    id: str
    beach_id: str
    name: str
    total_spaces: int
    available_spaces: int
    daily_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class ParkingPass(TypedDict):
    id: str
    lot_id: str
    plate: str
    vehicle_type: str
    pass_type: str
    is_resident: bool
    fee_cents: int
    status: str
    issued_at: str
    created_at: str
    updated_at: str
    version: int


# --- Entity with common_fields: false (append-only: id + created_at only) ---

class WaterQualitySample(TypedDict):
    id: str
    zone_id: str
    enterococci_mpn: int
    sampled_at: str
    lab_ref: str
    technician: str
    created_at: str
