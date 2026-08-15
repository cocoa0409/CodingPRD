"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    OPERATIONS_DIRECTOR = "OperationsDirector"
    FACILITY_COORDINATOR = "FacilityCoordinator"
    TECHNOLOGIST = "Technologist"
    READING_RADIOLOGIST = "ReadingRadiologist"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class Modality(str, Enum):
    MRI = "MRI"
    CT = "CT"
    PET = "PET"


class ExamType(str, Enum):
    CT_HEAD = "CT_HEAD"
    CT_CHEST = "CT_CHEST"
    MRI_BRAIN = "MRI_BRAIN"
    PET_ONCO = "PET_ONCO"


class BillingModel(str, Enum):
    PER_DAY = "PER_DAY"
    PER_SCAN = "PER_SCAN"


class UnitStatus(str, Enum):
    ACTIVE_SERVICE = "ACTIVE_SERVICE"
    MAINTENANCE = "MAINTENANCE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RoutePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class SiteDayStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EN_ROUTE = "EN_ROUTE"
    SETTING_UP = "SETTING_UP"
    READY = "READY"
    IN_SERVICE = "IN_SERVICE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"
    RESCHEDULED = "RESCHEDULED"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    SCANNING = "SCANNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class StaffingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class TransportLegStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    ARRIVED = "ARRIVED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ChecklistStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    ALL_PASSED = "ALL_PASSED"
    HAS_FAILURES = "HAS_FAILURES"


class BreakdownStatus(str, Enum):
    REPORTED = "REPORTED"
    RESOLVED = "RESOLVED"


class BreakdownSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class AccreditationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class StatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class ImageStudyStatus(str, Enum):
    QUEUED = "QUEUED"
    TRANSMITTING = "TRANSMITTING"
    DELIVERED = "DELIVERED"
    TRANSFER_FAILED = "TRANSFER_FAILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


# --- Entity TypedDicts (PRD §2.5 common fields: id, created_at, updated_at, version) ---


class ContractedFacility(TypedDict, total=False):
    id: str
    name: str
    address: str
    supported_modalities: List[str]
    pad_amps_available: int
    pad_voltage: int
    pad_level_tolerance_deg: float
    created_at: str
    updated_at: str
    version: int


class MobileImagingUnit(TypedDict, total=False):
    id: str
    unit_code: str
    modality: str
    power_required_amps: int
    voltage_required: int
    setup_minutes: int
    teardown_minutes: int
    home_base_name: str
    status: str
    active_breakdown_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceContract(TypedDict, total=False):
    id: str
    facility_id: str
    billing_model: str
    day_rate_cents: int
    scan_rate_cents: int
    included_scan_quota: int
    overage_scan_rate_cents: int
    guaranteed_minimum_cents: int
    no_show_fee_cents: int
    cancel_notice_hours: int
    cancel_late_pct: float
    monthly_scan_cap: int
    interruption_floor_cents: int
    created_at: str
    updated_at: str
    version: int


class RoutePlan(TypedDict, total=False):
    id: str
    unit_id: str
    week_start_date: str
    status: str
    supersedes_plan_id: Optional[str]
    site_day_count: int
    total_travel_stipend_cents: int
    created_at: str
    updated_at: str
    version: int


class SiteDayAssignment(TypedDict, total=False):
    id: str
    route_plan_id: str
    unit_id: str
    facility_id: str
    contract_id: str
    service_date: str
    arrival_time: str
    first_patient_time: str
    last_patient_time: str
    departure_time: str
    status: str
    cancel_reason: Optional[str]
    interrupt_reason: Optional[str]
    delivered_service_minutes: int
    rescheduled_from_id: Optional[str]
    rescheduled_to_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatientAppointment(TypedDict, total=False):
    id: str
    site_day_id: str
    patient_ref: str
    exam_type: str
    scheduled_start: str
    duration_minutes: int
    sedation_required: bool
    estimated_dose_msv: float
    insurance_preauth: Optional[str]
    status: str
    cancel_reason: Optional[str]
    completed_at: Optional[str]
    actual_dose_msv: float
    created_at: str
    updated_at: str
    version: int


class Technologist(TypedDict, total=False):
    id: str
    full_name: str
    modality_certs: List[str]
    home_base_name: str
    max_daily_drive_minutes: int
    current_day_dose_msv: float
    monthly_dose_msv: float
    created_at: str
    updated_at: str
    version: int


class StaffingAssignment(TypedDict, total=False):
    id: str
    site_day_id: str
    technologist_id: str
    estimated_drive_minutes: int
    projected_dose_msv: float
    status: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportLeg(TypedDict, total=False):
    id: str
    site_day_id: str
    origin_name: str
    destination_name: str
    distance_miles: float
    drive_minutes: int
    overnight: bool
    stipend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SetupChecklist(TypedDict, total=False):
    id: str
    site_day_id: str
    power_verify_passed: bool
    measured_amps: int
    pad_level_passed: bool
    chiller_passed: bool
    rf_shield_passed: bool
    network_link_passed: bool
    measured_uplink_mbps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BreakdownEvent(TypedDict, total=False):
    id: str
    unit_id: str
    site_day_id: Optional[str]
    severity: str
    description: str
    status: str
    downtime_hours: float
    resolution_notes: str
    created_at: str
    updated_at: str
    version: int


class AccreditationRecord(TypedDict, total=False):
    id: str
    unit_id: str
    accrediting_body: str
    modality: str
    issued_on: str
    expires_on: str
    status: str
    suspend_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict, total=False):
    id: str
    site_day_id: str
    contract_id: str
    billing_model_snapshot: str
    completed_scan_count: int
    no_show_count: int
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    credit_granted_cents: int
    credit_applied_cents: int
    net_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ImageStudy(TypedDict, total=False):
    id: str
    appointment_id: str
    study_uid: str
    size_mb: int
    transfer_attempts: int
    delivered_at: Optional[str]
    acknowledged_at: Optional[str]
    sla_breached: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RadiationDoseRecord(TypedDict, total=False):
    """Append-only (PRD §2.5): carries id + created_at only — no updated_at, no version."""

    id: str
    appointment_id: str
    technologist_id: str
    dose_msv: float
    drl_exceeded: bool
    created_at: str
