"""Domain types: entity TypedDicts, status enums, and the role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Patient, Clinician, TestPanel, LabOrder, Specimen, LabResult,
  CriticalNotification, RetestRequest are primary, top-level resources
  that carry id, created_at, updated_at, version.

- TransportLeg, AcknowledgementReceipt, ComplianceAuditEvent are
  append-only / immutable after creation and carry ONLY id and
  created_at — supplying or expecting updated_at or version on them is
  a contract error per PRD §2.4.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ORDERING_PROVIDER = "OrderingProvider"
    LAB_TECH = "LabTech"
    LAB_DIRECTOR = "LabDirector"


# ---------------------------------------------------------------------------
# Patient — PRD §3.1.
# ---------------------------------------------------------------------------
class NotificationConsent(str, Enum):
    SMS_AND_VOICE = "SMS_AND_VOICE"
    VOICE_ONLY = "VOICE_ONLY"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Clinician — PRD §3.1.
# ---------------------------------------------------------------------------
class ClinicianRoleKind(str, Enum):
    ORDERING_PROVIDER = "ORDERING_PROVIDER"
    LAB_TECH = "LAB_TECH"
    LAB_DIRECTOR = "LAB_DIRECTOR"


# ---------------------------------------------------------------------------
# TestPanel — PRD §3.1.
# ---------------------------------------------------------------------------
class CliaComplexity(str, Enum):
    WAIVED = "WAIVED"
    MODERATE = "MODERATE"
    HIGH = "HIGH"


class SpecimenType(str, Enum):
    BLOOD = "BLOOD"
    URINE = "URINE"
    CSF = "CSF"
    SWAB = "SWAB"


# ---------------------------------------------------------------------------
# LabOrder — PRD §3.2 / §3.3 / §3.4.
# ---------------------------------------------------------------------------
class LabOrderPriority(str, Enum):
    ROUTINE = "ROUTINE"
    STAT = "STAT"


class LabOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    COLLECTED = "COLLECTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    RESULTED = "RESULTED"
    RELEASED = "RELEASED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Specimen — PRD §3.3.
# ---------------------------------------------------------------------------
class SpecimenStatus(str, Enum):
    COLLECTED = "COLLECTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    REJECTED = "REJECTED"


class SpecimenRejectedReason(str, Enum):
    STABILITY_EXCEEDED = "STABILITY_EXCEEDED"
    CHAIN_BROKEN = "CHAIN_BROKEN"
    CONTAMINATED = "CONTAMINATED"
    INSUFFICIENT_VOLUME = "INSUFFICIENT_VOLUME"


# ---------------------------------------------------------------------------
# TransportLeg — PRD §3.3.
# ---------------------------------------------------------------------------
class TransportLegStatus(str, Enum):
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    BROKEN = "BROKEN"


# ---------------------------------------------------------------------------
# LabResult — PRD §3.4.
# ---------------------------------------------------------------------------
class LabResultStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    AMENDED = "AMENDED"
    RETRACTED = "RETRACTED"


# ---------------------------------------------------------------------------
# CriticalNotification — PRD §3.5.
# ---------------------------------------------------------------------------
class CriticalNotificationChannel(str, Enum):
    SMS = "SMS"
    VOICE = "VOICE"


class CriticalNotificationStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


# ---------------------------------------------------------------------------
# RetestRequest — PRD §3.7.
# ---------------------------------------------------------------------------
class RetestReason(str, Enum):
    SPECIMEN_REJECTED = "SPECIMEN_REJECTED"
    CRITICAL_UNACKNOWLEDGED = "CRITICAL_UNACKNOWLEDGED"
    RESULT_AMENDED = "RESULT_AMENDED"


class RetestStatus(str, Enum):
    ISSUED = "ISSUED"
    FULFILLED = "FULFILLED"
    CANCELED = "CANCELED"


# ---------------------------------------------------------------------------
# ComplianceAuditEvent — PRD §3.8.
# ---------------------------------------------------------------------------
class AuditEventType(str, Enum):
    ORDER_PLACED = "ORDER_PLACED"
    SPECIMEN_REJECTED = "SPECIMEN_REJECTED"
    RESULT_RELEASED = "RESULT_RELEASED"
    CRITICAL_NOTIFIED = "CRITICAL_NOTIFIED"
    CRITICAL_ACKED = "CRITICAL_ACKED"
    CRITICAL_ESCALATED = "CRITICAL_ESCALATED"
    RETEST_ISSUED = "RETEST_ISSUED"
    AMENDMENT_RECORDED = "AMENDMENT_RECORDED"


# ===========================================================================
# Primary entities — id + created_at + updated_at + version (PRD §2.4).
# ===========================================================================
class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    date_of_birth: str
    primary_phone_e164: str
    backup_phone_e164: Optional[str]
    notification_consent: str
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict, total=False):
    id: str
    npi: str
    full_name: str
    role_kind: str
    phone_e164: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class AnalyteSpec(TypedDict, total=False):
    analyte_code: str
    unit: str
    critical_low: Optional[float]
    critical_high: Optional[float]


class TestPanel(TypedDict, total=False):
    id: str
    code: str
    name: str
    clia_complexity: str
    specimen_type: str
    stability_minutes: int
    analytes: List[AnalyteSpec]
    created_at: str
    updated_at: str
    version: int


class LabOrder(TypedDict, total=False):
    id: str
    patient_id: str
    ordering_provider_id: str
    panel_id: str
    priority: str
    status: str
    retest_count: int
    parent_order_id: Optional[str]
    ordered_at: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict, total=False):
    id: str
    lab_order_id: str
    collected_by_id: str
    collected_at: str
    received_at: Optional[str]
    rejected_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CriticalFlag(TypedDict, total=False):
    analyte_code: str
    side: str
    value: float
    bound: float


class Measurement(TypedDict, total=False):
    analyte_code: str
    value: float
    unit: str


class LabResult(TypedDict, total=False):
    id: str
    lab_order_id: str
    resulted_by_id: str
    released_by_id: Optional[str]
    measurements: List[Measurement]
    critical_flags: List[CriticalFlag]
    severity_score: float
    status: str
    resulted_at: str
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CriticalNotification(TypedDict, total=False):
    id: str
    lab_result_id: str
    recipient_clinician_id: str
    channel: str
    attempt_count: int
    first_sent_at: str
    ack_deadline_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RetestRequest(TypedDict, total=False):
    id: str
    lab_order_id: str
    reason: str
    new_lab_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only entities — id + created_at only (PRD §2.4).
# ===========================================================================
class TransportLeg(TypedDict, total=False):
    id: str
    specimen_id: str
    leg_index: int
    from_location: str
    to_location: str
    departed_at: str
    arrived_at: Optional[str]
    courier_id: str
    status: str
    created_at: str


class AcknowledgementReceipt(TypedDict, total=False):
    id: str
    critical_notification_id: str
    acknowledged_by_id: str
    acknowledged_at: str
    read_back_text: str
    ack_latency_minutes: float
    created_at: str


class ComplianceAuditEvent(TypedDict, total=False):
    id: str
    event_type: str
    lab_order_id: str
    actor_id: str
    payload: Dict[str, Any]
    created_at: str


__all__ = [
    # Role enum
    "UserRole",
    # Status/enum types
    "NotificationConsent",
    "ClinicianRoleKind",
    "CliaComplexity",
    "SpecimenType",
    "LabOrderPriority",
    "LabOrderStatus",
    "SpecimenStatus",
    "SpecimenRejectedReason",
    "TransportLegStatus",
    "LabResultStatus",
    "CriticalNotificationChannel",
    "CriticalNotificationStatus",
    "RetestReason",
    "RetestStatus",
    "AuditEventType",
    # Entity TypedDicts
    "Patient",
    "Clinician",
    "AnalyteSpec",
    "TestPanel",
    "LabOrder",
    "Specimen",
    "CriticalFlag",
    "Measurement",
    "LabResult",
    "CriticalNotification",
    "RetestRequest",
    "TransportLeg",
    "AcknowledgementReceipt",
    "ComplianceAuditEvent",
]
