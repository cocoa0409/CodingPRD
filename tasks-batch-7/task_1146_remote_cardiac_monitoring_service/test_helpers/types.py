"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    """The seven roles recognized by the platform (PRD §2.1)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    ENROLLMENT_COORDINATOR = "EnrollmentCoordinator"
    PHYSICIAN = "Physician"
    MONITORING_TECHNICIAN = "MonitoringTechnician"
    BILLING_SPECIALIST = "BillingSpecialist"
    INVENTORY_MANAGER = "InventoryManager"
    DEVICE_GATEWAY = "DeviceGateway"


class InsurancePlan(str, Enum):
    MEDICARE = "MEDICARE"
    COMMERCIAL = "COMMERCIAL"
    SELF_PAY = "SELF_PAY"


class NotificationPreference(str, Enum):
    PHONE = "PHONE"
    PORTAL = "PORTAL"


class CertificationLevel(str, Enum):
    CCT = "CCT"
    CRAT = "CRAT"
    RN = "RN"


class DeviceModel(str, Enum):
    HOLTER = "HOLTER"
    EVENT = "EVENT"
    IMPLANTABLE = "IMPLANTABLE"


class DeviceStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    RETURN_IN_TRANSIT = "RETURN_IN_TRANSIT"
    REFURBISHING = "REFURBISHING"
    LOST = "LOST"


class OrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_SERVICE = "IN_SERVICE"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    INITIATED = "INITIATED"
    EDUCATED = "EDUCATED"
    ACTIVATION_FAILED = "ACTIVATION_FAILED"
    ACTIVATED = "ACTIVATED"
    ABORTED = "ABORTED"


class EducationMethod(str, Enum):
    IN_PERSON = "IN_PERSON"
    PHONE = "PHONE"
    VIDEO = "VIDEO"


class ClinicalStatus(str, Enum):
    MONITORING = "MONITORING"
    COMPLETED = "COMPLETED"
    TERMINATED_EARLY = "TERMINATED_EARLY"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class TransmissionStatus(str, Enum):
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"


class AlertSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class AlertStatus(str, Enum):
    NEW = "NEW"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    TRIAGED = "TRIAGED"
    ESCALATED = "ESCALATED"
    NOTIFIED = "NOTIFIED"
    CLOSED = "CLOSED"


class NotificationChannel(str, Enum):
    PHONE = "PHONE"
    PORTAL = "PORTAL"
    ESCALATION = "ESCALATION"


class NotificationAttemptStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ReportType(str, Enum):
    INTERIM = "INTERIM"
    FINAL = "FINAL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    AMENDED = "AMENDED"


class BillingPeriodStatus(str, Enum):
    ACCRUING = "ACCRUING"
    READY = "READY"
    SUBMITTED = "SUBMITTED"
    ADJUSTMENT_PROPOSED = "ADJUSTMENT_PROPOSED"
    ADJUSTED = "ADJUSTED"


class ShipmentStatus(str, Enum):
    LABEL_CREATED = "LABEL_CREATED"
    OVERDUE = "OVERDUE"
    RECEIVED = "RECEIVED"
    LOST = "LOST"


class ComplianceEventType(str, Enum):
    TRANSMISSION_GAP = "TRANSMISSION_GAP"
    RETURN_OVERDUE = "RETURN_OVERDUE"


class ComplianceEventStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ResolutionAction(str, Enum):
    CONTACTED_PATIENT = "CONTACTED_PATIENT"
    DEVICE_REPLACED = "DEVICE_REPLACED"
    PHYSICIAN_NOTIFIED = "PHYSICIAN_NOTIFIED"


class FatigueStatus(str, Enum):
    NORMAL = "NORMAL"
    AT_RISK = "AT_RISK"
    FATIGUED = "FATIGUED"


class ClosedOutcome(str, Enum):
    FALSE_POSITIVE = "FALSE_POSITIVE"
    RESOLVED = "RESOLVED"


class EpisodeCompleteReason(str, Enum):
    COMPLETED = "COMPLETED"
    TERMINATED_EARLY = "TERMINATED_EARLY"


# --- Entity TypedDicts (all resources carry id/created_at/updated_at/version, PRD §2.4) ---


class Patient(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    mrn: str
    phone: str
    insurance_plan: str
    open_compliance_events: int
    created_at: str
    updated_at: str
    version: int


class Physician(TypedDict, total=False):
    id: str
    full_name: str
    npi: str
    specialty: str
    notification_preference: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    certification_level: str
    shift_capacity: int
    on_shift: bool
    open_alert_load: int
    alerts_acknowledged_total: int
    fatigue_index: float
    throughput_index: float
    fatigue_status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    serial_number: str
    model: str
    status: str
    refurbishment_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringOrder(TypedDict, total=False):
    id: str
    patient_id: str
    ordering_physician_id: str
    monitor_type: str
    prescribed_days: int
    indication_codes: list
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    order_id: str
    device_id: str
    education_completed: bool
    education_method: Optional[str]
    status: str
    attempts_count: int
    episode_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringEpisode(TypedDict, total=False):
    id: str
    enrollment_id: str
    patient_id: str
    monitor_type: str
    started_at: str
    scheduled_end_at: str
    completed_at: Optional[str]
    clinical_status: str
    compliance_status: str
    strike_count: int
    transmission_count: int
    unacknowledged_critical_count: int
    total_billed_cents: int
    created_at: str
    updated_at: str
    version: int


class SuspensionInterval(TypedDict, total=False):
    id: str
    episode_id: str
    started_at: str
    ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Transmission(TypedDict, total=False):
    id: str
    episode_id: str
    seq_no: int
    bytes_received: int
    signal_quality: int
    received_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ArrhythmiaAlert(TypedDict, total=False):
    id: str
    episode_id: str
    severity: str
    arrhythmia_type: str
    detected_at: str
    sla_deadline: str
    status: str
    assigned_technician_id: Optional[str]
    acknowledged_at: Optional[str]
    closed_outcome: Optional[str]
    notification_attempt_count: int
    created_at: str
    updated_at: str
    version: int


class NotificationAttempt(TypedDict, total=False):
    id: str
    alert_id: str
    physician_id: str
    channel: str
    attempted_at: str
    status: str
    within_sla: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class DiagnosticReport(TypedDict, total=False):
    id: str
    episode_id: str
    reading_physician_id: str
    report_type: str
    findings_summary: str
    no_significant_findings: bool
    status: str
    revision_count: int
    finalized_at: Optional[str]
    turnaround_hours: Optional[float]
    sla_met: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict, total=False):
    id: str
    episode_id: str
    period_index: int
    start_date: str
    end_date: str
    window_days: int
    billable_days: Optional[int]
    provisional_total_cents: int
    tc_amount_cents: Optional[int]
    pc_amount_cents: Optional[int]
    total_amount_cents: Optional[int]
    status: str
    submitted_total_cents: Optional[int]
    proposed_delta_cents: Optional[int]
    proposed_by_user_id: Optional[str]
    approved_adjustment_cents: int
    approved_by_user_id: Optional[str]
    recognized_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ReturnShipment(TypedDict, total=False):
    id: str
    episode_id: str
    device_id: str
    label_created_at: str
    due_at: str
    received_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceEvent(TypedDict, total=False):
    id: str
    episode_id: str
    event_type: str
    status: str
    resolution_action: Optional[str]
    created_at: str
    updated_at: str
    version: int
