"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entities and lifecycle states described in the Vehicle Safety &
Emissions Inspection PRD.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles (PRD §2.1) — all four roles carry an opaque identity.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    STATION_MANAGER = "StationManager"
    INSPECTOR = "Inspector"
    RECEPTIONIST = "Receptionist"
    STATE_AUDITOR = "StateAuditor"


# ---------------------------------------------------------------------------
# Enumerations (PRD §2.10)
# ---------------------------------------------------------------------------
class VehicleClass(str, Enum):
    PASSENGER = "PASSENGER"
    LIGHT_TRUCK = "LIGHT_TRUCK"
    HEAVY_DUTY = "HEAVY_DUTY"
    MOTORCYCLE = "MOTORCYCLE"


class AppointmentKind(str, Enum):
    APPOINTMENT = "APPOINTMENT"
    WALK_IN = "WALK_IN"


class ChecklistOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NA = "NA"


class ChecklistSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class EmissionsProtocol(str, Enum):
    OBD2_CAN = "OBD2_CAN"
    OBD2_ISO = "OBD2_ISO"
    OBD2_J1850 = "OBD2_J1850"


class WaiverCostBasis(str, Enum):
    DOCUMENTED_ONLY = "DOCUMENTED_ONLY"
    DOCUMENTED_PLUS_ESTIMATED = "DOCUMENTED_PLUS_ESTIMATED"


# ---------------------------------------------------------------------------
# Lifecycle status enums (PRD §3)
# ---------------------------------------------------------------------------
class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class AnalyzerReservationStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"


class InspectionRecordStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"


class SafetyResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class EmissionsResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class EmissionsTestResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class RepairOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class WaiverRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class StateReportBatchStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class StateReportLineResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities carrying id + created_at + updated_at + version (common fields).
# ---------------------------------------------------------------------------
class Station(TypedDict):
    id: str
    name: str
    state_code: str
    certificate_serial_prefix: str
    next_certificate_seq: int
    repair_cost_limit_cents: int
    analyzer_count: int
    created_at: str
    updated_at: str
    version: int


class VehicleClassProfile(TypedDict):
    id: str
    station_id: str
    vehicle_class: str
    base_fee_cents: int
    obd_required: bool
    checklist_item_count: int
    reinspection_window_days: int
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict):
    id: str
    station_id: str
    lane_number: int
    supports_obd: bool
    turnaround_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class AnalyzerReservation(TypedDict):
    id: str
    station_id: str
    vehicle_vin: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    lane_id: str
    vehicle_vin: str
    vehicle_class: str
    kind: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionRecord(TypedDict):
    id: str
    appointment_id: str
    station_id: str
    vehicle_vin: str
    vehicle_class: str
    original_record_id: Optional[str]
    reinspection_index: int
    status: str
    safety_result: str
    emissions_result: str
    fee_cents: int
    waiver_applied: bool
    created_at: str
    updated_at: str
    version: int


class ChecklistResult(TypedDict):
    id: str
    record_id: str
    item_code: str
    outcome: str
    severity: str
    created_at: str
    updated_at: str
    version: int


class EmissionsTest(TypedDict):
    id: str
    record_id: str
    protocol: str
    dtc_count: int
    readiness_monitors_incomplete: int
    mil_on: bool
    result: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    record_id: str
    shop_name: str
    documented_cost_cents: int
    estimated_cost_cents: int
    emissions_related: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WaiverRequest(TypedDict):
    id: str
    record_id: str
    cost_basis: str
    qualifying_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    record_id: str
    serial: str
    sticker_number: str
    status: str
    expires_on: str
    created_at: str
    updated_at: str
    version: int


class StateReportBatch(TypedDict):
    id: str
    station_id: str
    period_label: str
    status: str
    line_count: int
    total_reported_fee_cents: int
    created_at: str
    updated_at: str
    version: int


# StateReportLine is immutable (PRD §2.4): only id + created_at, no version/updated_at.
class StateReportLine(TypedDict):
    id: str
    batch_id: str
    record_id: str
    reported_result: str
    fee_cents: int
    created_at: str
