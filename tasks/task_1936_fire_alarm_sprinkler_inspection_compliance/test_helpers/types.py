"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource in this API carries the
standard four system-managed fields (id, created_at, updated_at, version) per
the PRD's resource-identity section.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    FIRE_MARSHAL = "FireMarshal"
    CONTRACTOR_ADMIN = "ContractorAdmin"
    TECHNICIAN = "Technician"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class Posture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class NicetLevel(str, Enum):
    I = "I"
    II = "II"
    III = "III"
    IV = "IV"


class LicenseClass(str, Enum):
    ALARM = "ALARM"
    SPRINKLER = "SPRINKLER"
    BACKFLOW = "BACKFLOW"
    PUMP = "PUMP"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class OccupancyClass(str, Enum):
    ASSEMBLY = "ASSEMBLY"
    BUSINESS = "BUSINESS"
    EDUCATIONAL = "EDUCATIONAL"
    MERCANTILE = "MERCANTILE"
    RESIDENTIAL = "RESIDENTIAL"
    STORAGE = "STORAGE"


class PropertyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SystemCategory(str, Enum):
    FIRE_ALARM = "FIRE_ALARM"
    SPRINKLER = "SPRINKLER"
    BACKFLOW = "BACKFLOW"
    FIRE_PUMP = "FIRE_PUMP"


class ImpairmentStatus(str, Enum):
    NORMAL = "NORMAL"
    IMPAIRED = "IMPAIRED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class SystemStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class DeviceType(str, Enum):
    SMOKE_DETECTOR = "SMOKE_DETECTOR"
    PULL_STATION = "PULL_STATION"
    NOTIFICATION_APPLIANCE = "NOTIFICATION_APPLIANCE"
    SPRINKLER_HEAD = "SPRINKLER_HEAD"
    GAUGE_VALVE = "GAUGE_VALVE"
    FIRE_PUMP_CONTROLLER = "FIRE_PUMP_CONTROLLER"
    BACKFLOW_ASSEMBLY = "BACKFLOW_ASSEMBLY"
    SUPERVISORY_SWITCH = "SUPERVISORY_SWITCH"


class FrequencyCode(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    ANNUAL = "ANNUAL"


class DeviceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    REPLACED = "REPLACED"
    REMOVED = "REMOVED"


class PlanPosture(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FULFILLED = "FULFILLED"
    LAPSED = "LAPSED"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_ACCESS = "NO_ACCESS"


class DeficiencyClassification(str, Enum):
    CRITICAL = "CRITICAL"
    NONCRITICAL = "NONCRITICAL"


class DeficiencyStatus(str, Enum):
    OPEN = "OPEN"
    CORRECTED = "CORRECTED"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"


class ImpairmentKind(str, Enum):
    PLANNED = "PLANNED"
    UNPLANNED = "UNPLANNED"


class ImpairmentLifecycleStatus(str, Enum):
    OPEN = "OPEN"
    NOTIFIED = "NOTIFIED"
    RESTORED = "RESTORED"
    CLOSED = "CLOSED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class TestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class BackflowTestStatus(str, Enum):
    RECORDED = "RECORDED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    FAILED_OPEN = "FAILED_OPEN"


class PumpTestKind(str, Enum):
    CHURN = "CHURN"
    ANNUAL_FLOW = "ANNUAL_FLOW"


class PumpTestStatus(str, Enum):
    RECORDED = "RECORDED"
    ATTESTED = "ATTESTED"
    FAILED_OPEN = "FAILED_OPEN"


class CauseCode(str, Enum):
    NEGLIGENCE = "NEGLIGENCE"
    EQUIPMENT_FAULT = "EQUIPMENT_FAULT"
    UNKNOWN = "UNKNOWN"
    MALICIOUS = "MALICIOUS"
    WEATHER = "WEATHER"


class FalseAlarmStatus(str, Enum):
    OPEN = "OPEN"
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"
    PAID = "PAID"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    WORK_COMMENCED = "WORK_COMMENCED"
    FINED = "FINED"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class Contractor(TypedDict):
    id: str
    legal_name: str
    state_license_no: str
    compliance_score: int
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    contractor_id: str
    full_name: str
    nicet_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseRecord(TypedDict):
    id: str
    technician_id: str
    license_class: str
    issued_on: str
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    contractor_id: str
    address_line: str
    occupancy_class: str
    jurisdiction_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProtectedSystem(TypedDict):
    id: str
    property_id: str
    system_category: str
    install_date: str
    impairment_status: str
    certification_cycle_anchor: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    system_id: str
    device_type: str
    serial_no: str
    frequency_code: str
    next_due_date: str
    replaced_by_device_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionPlan(TypedDict):
    id: str
    property_id: str
    plan_year: int
    total_events_required: int
    events_completed: int
    plan_posture: str
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InspectionEvent(TypedDict):
    id: str
    plan_id: str
    system_id: str
    lead_technician_id: str
    scheduled_start: str
    scheduled_end: str
    completed_at: Optional[str]
    report_due_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Deficiency(TypedDict):
    id: str
    event_id: str
    device_id: str
    classification: str
    correction_deadline: Optional[str]
    extension_used: bool
    late_fee_cents: int
    corrected_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Impairment(TypedDict):
    id: str
    system_id: str
    impairment_kind: str
    planned_start: str
    planned_end: str
    notification_deadline: str
    authority_notified_at: Optional[str]
    notification_late: bool
    discovered_at: str
    restored_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarshalReport(TypedDict):
    id: str
    event_id: str
    portal_submission_id: Optional[str]
    submitted_at: Optional[str]
    is_late: bool
    revision_of_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class BackflowTest(TypedDict):
    id: str
    system_id: str
    device_id: str
    tester_technician_id: str
    tested_at: str
    result: str
    unpaid_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FirePumpTest(TypedDict):
    id: str
    system_id: str
    test_kind: str
    tester_technician_id: str
    tested_at: str
    result: str
    coordinated_event_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FalseAlarmCase(TypedDict):
    id: str
    property_id: str
    alarm_occurred_at: str
    cause_code: str
    chargeable: bool
    sequence_number: int
    fee_cents: int
    waived: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ModificationPermit(TypedDict):
    id: str
    system_id: str
    project_valuation_cents: int
    permit_fee_cents: int
    work_commenced_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
