"""Domain types for the Mental Health Counseling Platform.

Status enums and entity TypedDicts derived from PRD §2.4 (common fields),
§3 (entity narratives) and the role catalogue in PRD §2.1.

Per PRD §2.4: CounselingRecord, SettlementLedger, and AuditLogEntry carry only
`id` and `created_at` — they do NOT carry `updated_at` or `version`. Their
TypedDicts intentionally omit those fields.
"""
from __future__ import annotations
from enum import Enum
from typing import TypedDict, List, Optional, Any


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    Public = "Public"
    Client = "Client"
    Counselor = "Counselor"
    Supervisor = "Supervisor"
    CrisisResponder = "CrisisResponder"
    PlatformAdmin = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.1, §3.2, §3.3, §3.4, §3.5, §3.6, §3.7, §3.9, §3.10)
# ---------------------------------------------------------------------------
class CounselorStatus(str, Enum):
    PENDING_CERT = "PENDING_CERT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"


class ClientAssessmentStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ClientRiskFlag(str, Enum):
    NONE = "NONE"
    ELEVATED = "ELEVATED"
    ACUTE = "ACUTE"


class CertificationCycleStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class AvailabilitySlotStatus(str, Enum):
    OPEN = "OPEN"
    HELD = "HELD"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"
    RELEASED = "RELEASED"


class AppointmentStatus(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    RESCHEDULED = "RESCHEDULED"


class AppointmentType(str, Enum):
    INTAKE = "INTAKE"
    STANDARD = "STANDARD"
    FOLLOW_UP = "FOLLOW_UP"


class PaymentMode(str, Enum):
    PAY_PER_SESSION = "PAY_PER_SESSION"
    PACKAGE = "PACKAGE"


class RefundState(str, Enum):
    NONE = "NONE"
    FULL_REFUNDED = "FULL_REFUNDED"
    PARTIAL_REFUNDED = "PARTIAL_REFUNDED"
    NON_REFUNDABLE = "NON_REFUNDABLE"


class CancellationReason(str, Enum):
    CLIENT_CANCEL = "CLIENT_CANCEL"
    COUNSELOR_CANCEL = "COUNSELOR_CANCEL"
    CRISIS_HANDOVER = "CRISIS_HANDOVER"
    NO_SHOW_AUTO = "NO_SHOW_AUTO"


class Channel(str, Enum):
    TEXT = "TEXT"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"


class SpecialtyTag(str, Enum):
    ANXIETY = "ANXIETY"
    DEPRESSION = "DEPRESSION"
    TRAUMA = "TRAUMA"
    FAMILY = "FAMILY"
    ADDICTION = "ADDICTION"
    ADOLESCENT = "ADOLESCENT"
    EATING_DISORDER = "EATING_DISORDER"
    GRIEF = "GRIEF"


class CrisisIncidentStatus(str, Enum):
    DETECTED = "DETECTED"
    HANDED_OVER = "HANDED_OVER"
    EMERGENCY_NOTIFIED = "EMERGENCY_NOTIFIED"
    FOLLOW_UP_SCHEDULED = "FOLLOW_UP_SCHEDULED"
    RESOLVED = "RESOLVED"


class CrisisDetectionSource(str, Enum):
    KEYWORD_DETECTOR = "KEYWORD_DETECTOR"
    COUNSELOR_TRIGGERED = "COUNSELOR_TRIGGERED"


class CrisisSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SettlementDirection(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REVERSED = "REVERSED"


class SupervisionSessionStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CERecordStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CounselingRecordRedactionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PURGED = "PURGED"


class AuditAction(str, Enum):
    RECORD_READ = "RECORD_READ"
    RECORD_EXPORT = "RECORD_EXPORT"
    RECORD_PURGE = "RECORD_PURGE"
    CRISIS_DETECTED = "CRISIS_DETECTED"
    CRISIS_HANDOVER = "CRISIS_HANDOVER"
    CRISIS_NOTIFY = "CRISIS_NOTIFY"
    COUNSELOR_DISQUALIFIED = "COUNSELOR_DISQUALIFIED"
    RECERT_DECISION = "RECERT_DECISION"


# ---------------------------------------------------------------------------
# Entities with common fields (PRD §2.4): id, created_at, updated_at, version
# ---------------------------------------------------------------------------
class Counselor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    license_number: str
    license_expires_at: str
    specialty_tags: List[str]
    supported_channels: List[str]
    timezone: str
    status: str
    revenue_share_bps: int
    total_supervision_hours: float
    total_ce_hours: float
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    timezone: str
    emergency_contact_name: str
    emergency_contact_phone: str
    assessment_status: str
    package_balance_sessions: int
    risk_flag: str
    created_at: str
    updated_at: str
    version: int


class CertificationCycle(TypedDict, total=False):
    id: str
    counselor_id: str
    cycle_index: int
    required_supervision_hours: float
    required_ce_hours: float
    window_start_at: str
    window_end_at: str
    status: str
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AvailabilitySlot(TypedDict, total=False):
    id: str
    counselor_id: str
    start_at: str
    end_at: str
    channel: str
    status: str
    held_until: Optional[str]
    held_appointment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict, total=False):
    id: str
    counselor_id: str
    client_id: str
    slot_id: str
    appointment_type: str
    channel: str
    status: str
    payment_mode: str
    list_price_cents: int
    refund_state: str
    cancellation_reason: Optional[str]
    confirmed_at: Optional[str]
    started_at: Optional[str]
    ended_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrisisIncident(TypedDict, total=False):
    id: str
    appointment_id: str
    client_id: str
    detection_source: str
    trigger_keyword: Optional[str]
    severity: str
    status: str
    assigned_responder_id: Optional[str]
    handover_at: Optional[str]
    emergency_notified_at: Optional[str]
    follow_up_due_at: Optional[str]
    follow_up_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict, total=False):
    id: str
    counselor_id: str
    period_start_at: str
    period_end_at: str
    total_counselor_share_cents: int
    total_tax_cents: int
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupervisionSession(TypedDict, total=False):
    id: str
    counselor_id: str
    supervisor_id: str
    case_appointment_id: str
    scheduled_at: str
    duration_hours: float
    discussion_notes: str
    evaluation_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContinuingEducationRecord(TypedDict, total=False):
    id: str
    counselor_id: str
    course_title: str
    completed_at: str
    hours_claimed: float
    hours_credited: float
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / immutable entities (PRD §2.4): only id + created_at
# (NO updated_at, NO version)
# ---------------------------------------------------------------------------
class CounselingRecord(TypedDict, total=False):
    id: str
    appointment_id: str
    counselor_id: str
    client_id: str
    encrypted_note_blob: Optional[str]
    redaction_status: str
    retention_expires_at: str
    last_accessed_at: Optional[str]
    created_at: str


class SettlementLedger(TypedDict, total=False):
    id: str
    appointment_id: str
    direction: str
    gross_amount_cents: int
    tax_cents: int
    counselor_share_cents: int
    platform_share_cents: int
    payout_id: Optional[str]
    created_at: str


class AuditLogEntry(TypedDict, total=False):
    id: str
    actor_role: str
    actor_user_id: str
    action: str
    target_entity: str
    target_id: str
    payload_summary: Any
    created_at: str
