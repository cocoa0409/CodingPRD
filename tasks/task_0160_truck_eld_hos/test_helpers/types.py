"""Domain types: entity TypedDicts, status enums, role enum.

Common-fields entities (Driver, Carrier, Vehicle, ELDDevice, DailyLog,
Violation, AdverseConditionsExemption) carry id + created_at +
updated_at + version per PRD §2.4. The DutyEvent resource is an
"immutable audit record and carries only id and created_at; it has no
updated_at and no version" — its TypedDict therefore omits those two
fields.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    DRIVER = "Driver"
    CARRIER_SAFETY_OFFICER = "CarrierSafetyOfficer"
    FMCSA_AUDITOR = "FMCSAAuditor"
    PLATFORM_ADMIN = "PlatformAdmin"


# ===========================================================================
# Status / enum types
# ===========================================================================
class DutyStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    SLEEPER_BERTH = "SLEEPER_BERTH"
    DRIVING = "DRIVING"
    ON_DUTY_NOT_DRIVING = "ON_DUTY_NOT_DRIVING"
    PERSONAL_CONVEYANCE = "PERSONAL_CONVEYANCE"
    YARD_MOVES = "YARD_MOVES"


class CycleType(str, Enum):
    SEVENTY_HOUR_EIGHT_DAY = "SEVENTY_HOUR_EIGHT_DAY"
    SIXTY_HOUR_SEVEN_DAY = "SIXTY_HOUR_SEVEN_DAY"


class EditState(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class DailyLogStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    CERTIFIED = "CERTIFIED"
    RECERTIFIED = "RECERTIFIED"


class ViolationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REPORTED = "REPORTED"
    RESOLVED = "RESOLVED"


class ViolationRuleCode(str, Enum):
    ELEVEN_HOUR_DRIVING = "ELEVEN_HOUR_DRIVING"
    FOURTEEN_HOUR_WINDOW = "FOURTEEN_HOUR_WINDOW"
    SEVENTY_HOUR_CYCLE = "SEVENTY_HOUR_CYCLE"
    SIXTY_HOUR_CYCLE = "SIXTY_HOUR_CYCLE"


class ExemptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


# ===========================================================================
# Entity TypedDicts
# ===========================================================================
class Carrier(TypedDict, total=False):
    id: str
    dot_number: str
    legal_name: str
    safety_contact_user_id: str
    created_at: str
    updated_at: str
    version: int


class ELDDevice(TypedDict, total=False):
    id: str
    serial_number: str
    firmware_version: str
    certified_for_fmcsa: bool
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    carrier_id: str
    eld_device_id: str
    current_driver_id: Optional[str]
    odometer_miles: float
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    cdl_number: str
    full_name: str
    carrier_id: str
    cycle_type: str
    duty_status: str
    bound_vehicle_id: Optional[str]
    bound_eld_device_id: Optional[str]
    home_terminal_timezone: str
    last_34_hour_restart_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DutyEvent(TypedDict, total=False):
    # DutyEvent is append-only: PRD §2.4 names DutyEvent as carrying
    # only id and created_at — NO updated_at, NO version.
    id: str
    driver_id: str
    vehicle_id: Optional[str]
    new_status: str
    event_time: str
    latitude: float
    longitude: float
    odometer_miles: Optional[float]
    annotation: Optional[str]
    edit_state: str
    superseded_by_event_id: Optional[str]
    daily_log_id: str
    adverse_conditions_exemption_id: Optional[str]
    created_at: str


class DailyLog(TypedDict, total=False):
    id: str
    driver_id: str
    log_date: str
    status: str
    certified_at: Optional[str]
    certification_count: int
    total_driving_minutes: int
    total_on_duty_minutes: int
    integrity_hash: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Violation(TypedDict, total=False):
    id: str
    driver_id: str
    triggering_duty_event_id: str
    rule_code: str
    detected_at: str
    status: str
    reported_to_fmcsa_at: Optional[str]
    fmcsa_report_id: Optional[str]
    overage_minutes: int
    created_at: str
    updated_at: str
    version: int


class AdverseConditionsExemption(TypedDict, total=False):
    id: str
    driver_id: str
    declared_at: str
    reason: str
    status: str
    extra_minutes_granted: int
    applies_to_log_date: str
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "DutyStatus", "CycleType", "EditState",
    "DailyLogStatus",
    "ViolationStatus", "ViolationRuleCode",
    "ExemptionStatus",
    "Carrier", "ELDDevice", "Vehicle", "Driver",
    "DutyEvent", "DailyLog",
    "Violation", "AdverseConditionsExemption",
]
