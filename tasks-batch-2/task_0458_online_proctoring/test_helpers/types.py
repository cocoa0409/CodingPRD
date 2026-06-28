"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Online Proctoring PRD (§2.4, §3.1–§3.8). Entities carrying the
full audit triple (id + created_at + updated_at + version) get those fields;
the two append-only records (IdentityVerification, IncidentFlag) carry only
id + created_at — no updated_at, no version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Status enums ─────────────────────────────────────

class ProctorStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


class ExamStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MonitoringMode(str, Enum):
    LIVE = "LIVE"
    RECORD_REVIEW = "RECORD_REVIEW"


class AccommodationStatus(str, Enum):
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class AppointmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    CONSUMED = "CONSUMED"


class IdentityVerificationResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"
    REVIEW_HELD = "REVIEW_HELD"


class VoidReason(str, Enum):
    AUTO_THRESHOLD = "AUTO_THRESHOLD"
    ESCALATION_UPHELD = "ESCALATION_UPHELD"


class IncidentKind(str, Enum):
    LOCKDOWN_BREACH = "LOCKDOWN_BREACH"
    GAZE_OFF_SCREEN = "GAZE_OFF_SCREEN"
    SECOND_FACE = "SECOND_FACE"
    PROHIBITED_MATERIAL = "PROHIBITED_MATERIAL"
    NETWORK_DROP = "NETWORK_DROP"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentFlagStatus(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class EscalationVerdict(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    DELIVERED = "DELIVERED"


class ReportDisposition(str, Enum):
    CLEARED = "CLEARED"
    ESCALATED_TO_INSTITUTION = "ESCALATED_TO_INSTITUTION"


class RetakeStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    REBOOKED = "REBOOKED"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    SCHEDULING_COORDINATOR = "SchedulingCoordinator"
    PROCTOR = "Proctor"
    REVIEW_OFFICER = "ReviewOfficer"
    CANDIDATE = "Candidate"


# ─── Entity TypedDicts ────────────────────────────────

class Institution(TypedDict):
    id: str
    name: str
    report_threshold_score: float
    created_at: str
    updated_at: str
    version: int


class Proctor(TypedDict):
    id: str
    institution_id: str
    full_name: str
    concurrent_capacity: int
    active_session_count: int
    load_factor: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict):
    id: str
    institution_id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Exam(TypedDict):
    id: str
    institution_id: str
    title: str
    base_duration_minutes: int
    window_start_utc: str
    window_end_utc: str
    monitoring_mode: str
    lockdown_required: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Accommodation(TypedDict):
    id: str
    candidate_id: str
    exam_id: str
    extra_time_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    exam_id: str
    candidate_id: str
    proctor_id: str
    accommodation_id: Optional[str]
    scheduled_start_utc: str
    effective_duration_minutes: int
    effective_end_utc: str
    status: str
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class IdentityVerification(TypedDict):
    id: str
    appointment_id: str
    photo_id_match: bool
    room_scan_clear: bool
    result: str
    created_at: str


class ProctoringSession(TypedDict):
    id: str
    appointment_id: str
    proctor_id: str
    monitoring_mode: str
    integrity_score: float
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class IncidentFlag(TypedDict):
    id: str
    session_id: str
    kind: str
    severity: str
    status: str
    created_at: str


class Escalation(TypedDict):
    id: str
    session_id: str
    incident_flag_id: str
    opened_by_proctor_id: str
    review_officer_id: Optional[str]
    verdict: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IntegrityReport(TypedDict):
    id: str
    institution_id: str
    candidate_id: str
    exam_id: str
    session_ids: List[str]
    aggregate_score: float
    disposition: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RetakeAuthorization(TypedDict):
    id: str
    voided_session_id: str
    original_appointment_id: str
    replacement_appointment_id: Optional[str]
    authorized_by_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
