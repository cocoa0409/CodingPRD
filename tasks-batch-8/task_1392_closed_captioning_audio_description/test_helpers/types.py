"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    CLIENT_CONTACT = "ClientContact"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    CAPTION_EDITOR = "CaptionEditor"
    AD_PRODUCER = "ADProducer"
    QC_SPECIALIST = "QCSpecialist"
    SCHEDULER = "Scheduler"
    STENOGRAPHER = "Stenographer"
    OPERATIONS_MANAGER = "OperationsManager"


class ComplianceStandard(str, Enum):
    FCC_BROADCAST = "FCC_BROADCAST"
    SECTION_508 = "SECTION_508"
    INTERNAL = "INTERNAL"


class TurnaroundTier(str, Enum):
    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"
    RUSH = "RUSH"
    SAME_DAY = "SAME_DAY"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class IntakeStatus(str, Enum):
    RECEIVED = "RECEIVED"
    INSPECTING = "INSPECTING"
    CLEARED = "CLEARED"
    REJECTED_INTAKE = "REJECTED_INTAKE"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    QUOTE_EXPIRED = "QUOTE_EXPIRED"
    CONFIRMED = "CONFIRMED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY_FOR_DELIVERY = "READY_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    REMEDIATION = "REMEDIATION"
    CLIENT_ACCEPTED = "CLIENT_ACCEPTED"
    CANCELLED = "CANCELLED"


class TrackStatus(str, Enum):
    AUTHORING = "AUTHORING"
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    QC_QUEUED = "QC_QUEUED"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    QC_FAILED_PERMANENT = "QC_FAILED_PERMANENT"
    CONFORMED = "CONFORMED"
    DELIVERED = "DELIVERED"
    DISPUTED = "DISPUTED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class ADStatus(str, Enum):
    SCRIPTING = "SCRIPTING"
    SCRIPT_REVIEW = "SCRIPT_REVIEW"
    RECORDING = "RECORDING"
    MIX_QC = "MIX_QC"
    CONFORMED = "CONFORMED"
    DELIVERED = "DELIVERED"
    DISPUTED = "DISPUTED"
    ARCHIVED = "ARCHIVED"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BRIEFED = "BRIEFED"
    ON_AIR = "ON_AIR"
    WRAP = "WRAP"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class StenoStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CERTIFICATION_LAPSED = "CERTIFICATION_LAPSED"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    OFFER_EXPIRED = "OFFER_EXPIRED"
    CONFIRMED = "CONFIRMED"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    PREEMPTED = "PREEMPTED"
    CANCELLED = "CANCELLED"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    REMEDIATING = "REMEDIATING"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"
    REOPENED = "REOPENED"


class JobStatus(str, Enum):
    QUEUED = "QUEUED"
    CONVERTING = "CONVERTING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    FAILED_VALIDATION = "FAILED_VALIDATION"
    CANCELLED = "CANCELLED"


class ArchiveStatus(str, Enum):
    ACTIVE_HOLD = "ACTIVE_HOLD"
    COLD_STORE = "COLD_STORE"
    RESTORE_PENDING = "RESTORE_PENDING"
    RESTORED_HOT = "RESTORED_HOT"
    PURGED = "PURGED"


class RetentionClass(str, Enum):
    REGULATED_BROADCAST = "REGULATED_BROADCAST"
    LIVE_ONLY = "LIVE_ONLY"
    STANDARD = "STANDARD"


class Client(TypedDict, total=False):
    id: str
    name: str
    compliance_standard: str
    default_turnaround_tier: str
    client_status: str
    ytd_completed_minutes: int
    created_at: str
    updated_at: str
    version: int


class MediaAsset(TypedDict, total=False):
    id: str
    client_id: str
    title: str
    media_kind: str
    duration_seconds: int
    frame_rate: str
    intake_status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    client_id: str
    media_asset_id: str
    service_type: str
    turnaround_tier: str
    language: str
    order_status: str
    quoted_price_cents: Optional[int]
    quote_expires_at: Optional[str]
    due_at: Optional[str]
    sla_breached: bool
    delivered_at: Optional[str]
    active_complaint_count: int
    created_at: str
    updated_at: str
    version: int


class CaptionTrack(TypedDict, total=False):
    id: str
    work_order_id: str
    supersedes_track_id: Optional[str]
    version_no: int
    language: str
    caption_format: str
    speaker_id_style: str
    track_status: str
    author_user_id: str
    qc_attempts: int
    last_accuracy_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class QCReview(TypedDict, total=False):
    # Immutable measurement record: carries only id + created_at (PRD §2.4).
    id: str
    created_at: str
    caption_track_id: str
    reviewer_user_id: str
    review_mode: str
    total_words: int
    sampled_words: Optional[int]
    minor_errors: int
    major_errors: int
    critical_errors: int
    weighted_errors: int
    accuracy_pct: float
    threshold_pct: float
    outcome: str


class AudioDescriptionTrack(TypedDict, total=False):
    id: str
    work_order_id: str
    language: str
    narrator_name: str
    author_user_id: str
    ad_status: str
    gaps: List[Dict[str, Any]]
    segments: List[Dict[str, Any]]
    gap_coverage_pct: Optional[float]
    studio_id: Optional[str]
    record_start_at: Optional[str]
    record_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LiveEvent(TypedDict, total=False):
    id: str
    client_id: str
    title: str
    channel_id: str
    start_at: str
    end_at: str
    required_certification: str
    prep_minutes: int
    wrap_minutes: int
    event_status: str
    created_at: str
    updated_at: str
    version: int


class Stenographer(TypedDict, total=False):
    id: str
    display_name: str
    certification: str
    certified_since: str
    cert_valid_until: str
    max_daily_live_minutes: int
    steno_status: str
    make_up_minutes_credited: int
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class LiveAssignment(TypedDict, total=False):
    id: str
    live_event_id: str
    stenographer_id: str
    assignment_status: str
    origin: str
    offered_at: str
    offer_expires_at: str
    booked_minutes: int
    preemption_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    client_id: str
    caption_track_id: Optional[str]
    audio_description_track_id: Optional[str]
    live_event_id: Optional[str]
    severity: str
    description: str
    complaint_status: str
    escalation_level: int
    remediation_track_id: Optional[str]
    resolved_at: Optional[str]
    resolver_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConversionJob(TypedDict, total=False):
    id: str
    source_track_id: str
    target_format: str
    embed: bool
    job_status: str
    attempt_count: int
    output_duration_ms: Optional[int]
    last_delta_ms: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ArchiveItem(TypedDict, total=False):
    id: str
    caption_track_id: Optional[str]
    audio_description_track_id: Optional[str]
    live_event_id: Optional[str]
    retention_class: str
    archive_status: str
    archived_at: Optional[str]
    purge_after: Optional[str]
    legal_hold: bool
    dispute_freeze: bool
    created_at: str
    updated_at: str
    version: int
