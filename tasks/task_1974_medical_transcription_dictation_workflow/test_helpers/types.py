"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    VENDOR_ADMIN = "VendorAdmin"
    CLIENT_ADMIN = "ClientAdmin"
    PROVIDER = "Provider"
    EDITOR = "Editor"
    QA_SUPERVISOR = "QASupervisor"


class Priority(str, Enum):
    STAT = "STAT"
    URGENT = "URGENT"
    ROUTINE = "ROUTINE"


class WorkType(str, Enum):
    CONSULT = "CONSULT"
    OP_NOTE = "OP_NOTE"
    DISCHARGE_SUMMARY = "DISCHARGE_SUMMARY"
    CLINIC_NOTE = "CLINIC_NOTE"
    RADIOLOGY_REPORT = "RADIOLOGY_REPORT"


class Specialty(str, Enum):
    RADIOLOGY = "RADIOLOGY"
    CARDIOLOGY = "CARDIOLOGY"
    ORTHOPEDICS = "ORTHOPEDICS"
    GENERAL = "GENERAL"


class MeasurementBasis(str, Enum):
    END_TO_END = "END_TO_END"
    PRODUCTION_WINDOW = "PRODUCTION_WINDOW"


class JobWorkflowStatus(str, Enum):
    QUEUED = "QUEUED"
    EDITING = "EDITING"
    SUBMITTED = "SUBMITTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class EscalationLevel(str, Enum):
    NONE = "NONE"
    ESCALATED = "ESCALATED"
    CRITICAL = "CRITICAL"


class EditorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class SkillTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ProviderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WARNING = "WARNING"
    SUSPENDED = "SUSPENDED"


class TranscriptStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    RETURNED = "RETURNED"
    SIGNED = "SIGNED"
    AMENDED = "AMENDED"


class AgingTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class LineItemStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    CREDIT_REVERSED = "CREDIT_REVERSED"


class MacroStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class QAOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    REVERSED = "REVERSED"


class ClinicAccount(TypedDict):
    id: str
    name: str
    unsigned_report_threshold: int
    aging_tier1_hours: int
    aging_tier2_hours: int
    payment_grace_days: int
    billing_hold: bool
    suspended_provider_count: int
    created_at: str
    updated_at: str
    version: int


class SLAPolicy(TypedDict):
    id: str
    clinic_account_id: str
    priority: str
    tat_minutes: int
    rate_per_line_cents: int
    breach_credit_pct: int
    measurement_basis: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    clinic_account_id: str
    full_name: str
    specialty: str
    status: str
    unsigned_tier1_count: int
    unsigned_aged_count: int
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Editor(TypedDict):
    id: str
    display_name: str
    status: str
    rolling_quality_score: float
    qa_review_count: int
    skill_tier: str
    max_concurrent_claims: int
    active_claim_count: int
    created_at: str
    updated_at: str
    version: int


class EditorShiftWindow(TypedDict):
    id: str
    editor_id: str
    start_at: str
    end_at: str
    created_at: str
    updated_at: str
    version: int


class DictationJob(TypedDict):
    id: str
    provider_id: str
    clinic_account_id: str
    work_type: str
    priority: str
    audio_duration_seconds: int
    template_id: Optional[str]
    workflow_status: str
    escalation_level: str
    claimed_by_editor_id: Optional[str]
    first_claimed_at: Optional[str]
    claimed_at: Optional[str]
    submitted_at: Optional[str]
    delivered_at: Optional[str]
    due_at: str
    asr_char_estimate: int
    rework_count: int
    preempted_count: int
    created_at: str
    updated_at: str
    version: int


class Transcript(TypedDict):
    id: str
    dictation_job_id: str
    editor_id: str
    version_number: int
    final_text: str
    visible_char_count: int
    line_count: int
    status: str
    aging_tier: str
    delivered_at: Optional[str]
    signed_at: Optional[str]
    addendum_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only event record (PRD §2.5): carries ONLY id + created_at as common
# fields — no updated_at, no version.
class QAReview(TypedDict):
    id: str
    created_at: str
    dictation_job_id: str
    transcript_id: str
    reviewer_user_id: str
    critical_error_count: int
    major_error_count: int
    minor_error_count: int
    accuracy_score: float
    outcome: str
    editor_sequence: int


class ProviderTemplate(TypedDict):
    id: str
    provider_id: str
    work_type: str
    name: str
    body_text: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Macro(TypedDict):
    id: str
    provider_id: str
    shortcut: str
    expansion_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict):
    id: str
    clinic_account_id: str
    period_start: str
    period_end: str
    status: str
    gross_amount_cents: int
    credit_amount_cents: int
    net_amount_cents: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LineItem(TypedDict):
    id: str
    billing_period_id: str
    transcript_id: str
    priority: str
    rate_per_line_cents: int
    provisional_line_count: int
    provisional_amount_cents: int
    final_line_count: Optional[int]
    final_amount_cents: Optional[int]
    sla_breach: Optional[bool]
    credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
