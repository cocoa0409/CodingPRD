"""Domain types: entity TypedDicts, status enums, role enum.

Field names and statuses are taken verbatim from the PRD (§2, §3).
Every entity in this system carries the common fields id, created_at,
updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums (PRD §3 state machines) ─────────────────────────────

class CenterPosture(str, Enum):
    OPEN = "OPEN"
    QUALITY_HOLD = "QUALITY_HOLD"
    LOCKED = "LOCKED"


class ModalityType(str, Enum):
    MRI = "MRI"
    CT = "CT"
    XRAY = "XRAY"
    US = "US"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class StaffRole(str, Enum):
    TECHNOLOGIST = "TECHNOLOGIST"
    RADIOLOGIST = "RADIOLOGIST"
    NURSE = "NURSE"


class OrderPriority(str, Enum):
    STAT = "STAT"
    ROUTINE = "ROUTINE"


class OrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    BENEFIT_CHECKED = "BENEFIT_CHECKED"
    SCREEN_CLEARED = "SCREEN_CLEARED"
    SCHEDULED = "SCHEDULED"
    READ_PENDING = "READ_PENDING"
    SIGNED_OFF = "SIGNED_OFF"
    ADDENDUM_REQUESTED = "ADDENDUM_REQUESTED"
    CANCELLED = "CANCELLED"


class PriorAuthStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    DENIED = "DENIED"


class ScreeningOutcome(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class BlockingReason(str, Enum):
    PREGNANCY = "PREGNANCY"
    METAL_IMPLANT = "METAL_IMPLANT"
    CONTRAST_ALLERGY = "CONTRAST_ALLERGY"
    RENAL_FUNCTION = "RENAL_FUNCTION"


class ExamStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    ACQUIRING = "ACQUIRING"
    ACQUIRED = "ACQUIRED"
    READING = "READING"
    READ_COMPLETE = "READ_COMPLETE"
    SIGNED_OFF = "SIGNED_OFF"
    CANCELLED = "CANCELLED"


class SeriesOutcome(str, Enum):
    CAPTURING = "CAPTURING"
    ACCEPTED = "ACCEPTED"
    REPEATED = "REPEATED"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    MOTION = "MOTION"
    POSITIONING = "POSITIONING"
    EXPOSURE = "EXPOSURE"
    ARTIFACT = "ARTIFACT"
    EQUIPMENT = "EQUIPMENT"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    AMENDED = "AMENDED"


class NotifiedPartyRole(str, Enum):
    ORDERING_PROVIDER = "ORDERING_PROVIDER"
    COVERING_PROVIDER = "COVERING_PROVIDER"
    RAPID_RESPONSE = "RAPID_RESPONSE"


class CriticalResultStatus(str, Enum):
    UNACKNOWLEDGED = "UNACKNOWLEDGED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class UserRole(str, Enum):
    CENTER_ADMIN = "CenterAdmin"
    SCHEDULING_CLERK = "SchedulingClerk"
    NURSE = "Nurse"
    TECHNOLOGIST = "Technologist"
    RADIOLOGIST = "Radiologist"


# ─── Entity TypedDicts (all entities common_fields: true, PRD §2.4) ────

class ImagingCenter(TypedDict):
    id: str
    name: str
    time_zone: str
    now_utc: str
    critical_ack_sla_minutes: int
    repeat_rate_threshold_pct: float
    admin_locked: bool
    posture: str
    total_acquired_series: int
    total_repeat_reject_series: int
    repeat_reject_rate_pct: float
    created_at: str
    updated_at: str
    version: int


class Modality(TypedDict):
    id: str
    imaging_center_id: str
    modality_type: str
    name: str
    base_rvu: float
    requires_contrast_screening: bool
    requires_prior_auth: bool
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    imaging_center_id: str
    modality_id: str
    name: str
    cleanup_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Staff(TypedDict):
    id: str
    imaging_center_id: str
    staff_role: str
    full_name: str
    credentialed_modalities: List[str]
    signed_rvu_total: float
    created_at: str
    updated_at: str
    version: int


class ImagingOrder(TypedDict):
    id: str
    imaging_center_id: str
    modality_id: str
    patient_mrn: str
    ordering_provider_npi: str
    priority: str
    requires_contrast: bool
    status: str
    report_turnaround_minutes: Optional[float]
    turnaround_met: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class PriorAuthorization(TypedDict):
    id: str
    imaging_order_id: str
    payer_name: str
    requested_units: int
    authorized_units: int
    benefit_copay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ContrastScreening(TypedDict):
    id: str
    imaging_order_id: str
    egfr_value: float
    has_contrast_allergy: bool
    is_pregnant: bool
    metal_implant_unsafe: bool
    outcome: str
    blocking_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImagingExam(TypedDict):
    id: str
    imaging_order_id: str
    room_id: str
    technologist_id: str
    radiologist_id: Optional[str]
    scheduled_start_utc: str
    scheduled_end_utc: str
    acquired_at_utc: Optional[str]
    signed_off_at_utc: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ImageSeries(TypedDict):
    id: str
    imaging_exam_id: str
    imaging_center_id: str
    series_label: str
    outcome: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RadiologyReport(TypedDict):
    id: str
    imaging_exam_id: str
    radiologist_id: str
    findings_text: str
    has_critical_finding: bool
    rvu_credited: float
    addendum_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CriticalResult(TypedDict):
    id: str
    radiology_report_id: str
    imaging_center_id: str
    notified_party_role: str
    raised_at_utc: str
    acknowledged_at_utc: Optional[str]
    minutes_to_ack: Optional[float]
    sla_breached: bool
    status: str
    created_at: str
    updated_at: str
    version: int
