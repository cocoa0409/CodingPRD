"""Domain types: entity TypedDicts, status enums, role enum (PRD §3.1–§3.8).

PRD §2.4: every entity carries a server-minted `id`. Entities with the common
lifecycle additionally carry `created_at`, `updated_at`, and `version`. The
`AcknowledgementReceipt` is the lone exception — it is immutable by design and
exposes only `id` and `created_at` (PRD §2.4).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Enums ───────────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    ORDERING_PROVIDER = "OrderingProvider"
    PHLEBOTOMIST = "Phlebotomist"
    LAB_TECH = "LabTech"
    LAB_DIRECTOR = "LabDirector"


class ClinicianRoleType(str, Enum):
    ORDERING_PROVIDER = "ORDERING_PROVIDER"
    PHLEBOTOMIST = "PHLEBOTOMIST"
    LAB_TECH = "LAB_TECH"
    LAB_DIRECTOR = "LAB_DIRECTOR"


class AgeBand(str, Enum):
    NEONATE = "NEONATE"
    INFANT = "INFANT"
    PEDIATRIC = "PEDIATRIC"
    ADULT = "ADULT"


class PanelCode(str, Enum):
    CMP = "CMP"
    CBC = "CBC"
    TROP = "TROP"
    GLUC = "GLUC"


class LabOrderPriority(str, Enum):
    STAT = "STAT"
    ROUTINE = "ROUTINE"


class LabOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ACCESSIONED = "ACCESSIONED"
    RESULTED = "RESULTED"
    CANCELLED = "CANCELLED"


class ContainerCode(str, Enum):
    RED = "RED"
    LAVENDER = "LAVENDER"
    GREEN = "GREEN"
    GRAY = "GRAY"


class SpecimenStatus(str, Enum):
    DRAFT = "DRAFT"
    COLLECTED = "COLLECTED"
    IN_TRANSIT = "IN_TRANSIT"
    ACCESSIONED = "ACCESSIONED"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    HEMOLYZED = "HEMOLYZED"
    CLOTTED = "CLOTTED"
    INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"
    MISLABELED = "MISLABELED"


class InstrumentRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class AnalyteCode(str, Enum):
    K = "K"
    GLUCOSE = "GLUCOSE"
    TROPONIN = "TROPONIN"
    HGB = "HGB"


class Criticality(str, Enum):
    NORMAL = "NORMAL"
    ABNORMAL = "ABNORMAL"
    CRITICAL_LOW = "CRITICAL_LOW"
    CRITICAL_HIGH = "CRITICAL_HIGH"
    PANIC = "PANIC"


class ResultStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RELEASED = "RELEASED"
    AMENDED = "AMENDED"
    INVALIDATED = "INVALIDATED"


class NotificationChannel(str, Enum):
    SMS = "SMS"
    PHONE = "PHONE"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class AckMethod(str, Enum):
    SMS_REPLY = "SMS_REPLY"
    IVR_KEYPRESS = "IVR_KEYPRESS"
    WEB_UI = "WEB_UI"


class RetestReason(str, Enum):
    DELTA_CHECK_FAIL = "DELTA_CHECK_FAIL"
    CLINICIAN_DOUBT = "CLINICIAN_DOUBT"
    INSTRUMENT_QC_FAIL = "INSTRUMENT_QC_FAIL"


class RetestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts (PRD §3.1–§3.8) ───────────────────────────────────────


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    age_band: str
    results_release_count: int
    critical_incidents_count: int
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict, total=False):
    id: str
    npi: str
    full_name: str
    role_type: str
    phone_e164: str
    backup_clinician_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict, total=False):
    id: str
    patient_id: str
    ordering_clinician_id: str
    panel_code: str
    priority: str
    status: str
    ordered_at: str
    specimens_count: int
    accessioned_count: int
    turn_around_time_minutes: Optional[int]
    compliance_incident: bool
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict, total=False):
    id: str
    lab_order_id: str
    collector_clinician_id: str
    container_code: str
    status: str
    collected_at: Optional[str]
    accessioned_at: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict, total=False):
    id: str
    instrument_code: str
    analyte_panels_supported: List[str]
    qc_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class InstrumentRun(TypedDict, total=False):
    id: str
    instrument_id: str
    specimen_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Result(TypedDict, total=False):
    id: str
    lab_order_id: str
    specimen_id: str
    run_id: str
    analyte_code: str
    numeric_value: float
    unit: str
    reference_low: float
    reference_high: float
    critical_low: float
    critical_high: float
    criticality: str
    status: str
    released_at: Optional[str]
    amended_from_result_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CriticalNotification(TypedDict, total=False):
    id: str
    result_id: str
    recipient_clinician_id: str
    channel: str
    status: str
    sent_at: Optional[str]
    ack_deadline_at: Optional[str]
    attempt_count: int
    escalation_target_clinician_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# AcknowledgementReceipt — PRD §2.4: immutable, carries ONLY id + created_at.
# No updated_at, no version.
class AcknowledgementReceipt(TypedDict, total=False):
    id: str
    critical_notification_id: str
    acknowledging_clinician_id: str
    ack_method: str
    attestation_text: str
    created_at: str


class RetestRequest(TypedDict, total=False):
    id: str
    original_result_id: str
    new_order_id: Optional[str]
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
