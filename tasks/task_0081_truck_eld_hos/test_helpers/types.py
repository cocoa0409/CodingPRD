"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource definitions (PRD §2.4, §3). Append-only audit
records (PersonalConveyanceSegment) carry only id + created_at per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    DRIVER = "Driver"
    CARRIER_ADMIN = "CarrierAdmin"
    SAFETY_OFFICER = "SafetyOfficer"


# --- Status / enum value sets ---
class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class CycleRule(str, Enum):
    SEVENTY_HOUR_8_DAY = "SEVENTY_HOUR_8_DAY"
    SIXTY_HOUR_7_DAY = "SIXTY_HOUR_7_DAY"


class DutyStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    SLEEPER_BERTH = "SLEEPER_BERTH"
    DRIVING = "DRIVING"
    ON_DUTY_NOT_DRIVING = "ON_DUTY_NOT_DRIVING"


class SpecialDrivingCategory(str, Enum):
    NONE = "NONE"
    PERSONAL_CONVEYANCE = "PERSONAL_CONVEYANCE"
    YARD_MOVE = "YARD_MOVE"


class VehicleStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DeviceStatus(str, Enum):
    UNBOUND = "UNBOUND"
    BOUND = "BOUND"
    MALFUNCTION = "MALFUNCTION"


class RecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE_CHANGED = "INACTIVE_CHANGED"
    INACTIVE_ERROR = "INACTIVE_ERROR"


class ComplianceDisposition(str, Enum):
    COMPLIANT = "COMPLIANT"
    VIOLATING = "VIOLATING"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    RECERTIFY_REQUIRED = "RECERTIFY_REQUIRED"


class ViolationType(str, Enum):
    DRIVING_11H = "DRIVING_11H"
    WINDOW_14H = "WINDOW_14H"
    CYCLE_70H = "CYCLE_70H"
    BREAK_30MIN = "BREAK_30MIN"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class ClaimReason(str, Enum):
    WEATHER = "WEATHER"
    ROAD_CLOSURE = "ROAD_CLOSURE"
    TRAFFIC_INCIDENT = "TRAFFIC_INCIDENT"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# --- Entity TypedDicts ---
# Entities carrying common fields: id + created_at + updated_at + version.
class Driver(TypedDict):
    id: str
    license_number: str
    full_name: str
    home_terminal_tz_offset_minutes: int
    cycle_rule: str
    status: str
    pc_authorized: bool
    current_duty_status: str
    cycle_on_duty_minutes: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    unit_number: str
    vin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ELDDevice(TypedDict):
    id: str
    serial_number: str
    vehicle_id: str
    bound_driver_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DutyStatusEvent(TypedDict):
    id: str
    driver_id: str
    device_id: str
    vehicle_id: str
    duty_status: str
    special_driving_category: str
    event_time: str
    duration_minutes: Optional[int]
    record_status: str
    compliance_disposition: str
    edited_from_event_id: Optional[str]
    annotation: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DailyLog(TypedDict):
    id: str
    driver_id: str
    log_date: str
    total_driving_minutes: int
    total_on_duty_minutes: int
    total_off_duty_minutes: int
    certification_status: str
    certified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HOSViolation(TypedDict):
    id: str
    driver_id: str
    trigger_event_id: str
    violation_type: str
    overage_minutes: int
    status: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdverseConditionsClaim(TypedDict):
    id: str
    driver_id: str
    log_date: str
    reason: str
    narrative: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit record (PRD §2.4): id + created_at only. No updated_at, no version.
class PersonalConveyanceSegment(TypedDict):
    id: str
    driver_id: str
    event_id: str
    minutes_excluded: int
    created_at: str
