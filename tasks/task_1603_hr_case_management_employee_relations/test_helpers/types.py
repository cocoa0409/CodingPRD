"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ER_MANAGER = "ERManager"
    INVESTIGATOR = "Investigator"
    LEGAL_COUNSEL = "LegalCounsel"
    HR_ANALYST = "HRAnalyst"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class CertificationLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class ChannelCode(str, Enum):
    HOTLINE = "HOTLINE"
    WEB_PORTAL = "WEB_PORTAL"
    MANAGER_REFERRAL = "MANAGER_REFERRAL"
    HR_DIRECT = "HR_DIRECT"
    ANONYMOUS_LETTER = "ANONYMOUS_LETTER"


class CaseCategory(str, Enum):
    HARASSMENT = "HARASSMENT"
    DISCRIMINATION = "DISCRIMINATION"
    RETALIATION = "RETALIATION"
    POLICY_VIOLATION = "POLICY_VIOLATION"
    SAFETY = "SAFETY"
    COMPENSATION = "COMPENSATION"
    OTHER = "OTHER"


class CaseSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CaseStatus(str, Enum):
    TRIAGE = "TRIAGE"
    ASSIGNED = "ASSIGNED"
    INVESTIGATING = "INVESTIGATING"
    FINDINGS_DRAFT = "FINDINGS_DRAFT"
    CALIBRATION = "CALIBRATION"
    PENDING_CLOSURE = "PENDING_CLOSURE"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"
    ON_HOLD = "ON_HOLD"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class EvidenceType(str, Enum):
    DOCUMENT = "DOCUMENT"
    EMAIL = "EMAIL"
    CHAT_LOG = "CHAT_LOG"
    PHOTO = "PHOTO"
    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    PHYSICAL = "PHYSICAL"
    TESTIMONY = "TESTIMONY"


class EvidenceStatus(str, Enum):
    LOGGED = "LOGGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADMITTED = "ADMITTED"
    EXCLUDED = "EXCLUDED"
    ARCHIVED = "ARCHIVED"


class SubstantiationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBSTANTIATED = "SUBSTANTIATED"
    UNSUBSTANTIATED = "UNSUBSTANTIATED"
    INCONCLUSIVE = "INCONCLUSIVE"


class ApprovalStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CALIBRATED = "CALIBRATED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"


class ActionType(str, Enum):
    NO_ACTION = "NO_ACTION"
    COACHING = "COACHING"
    WRITTEN_WARNING = "WRITTEN_WARNING"
    FINAL_WARNING = "FINAL_WARNING"
    SUSPENSION = "SUSPENSION"
    DEMOTION = "DEMOTION"
    TERMINATION = "TERMINATION"
    POLICY_CHANGE = "POLICY_CHANGE"


class ActionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class RecipientRole(str, Enum):
    REPORTER = "REPORTER"
    SUBJECT = "SUBJECT"


class ConfidentialityTier(str, Enum):
    TIER_1_SUMMARY = "TIER_1_SUMMARY"
    TIER_2_LIMITED = "TIER_2_LIMITED"
    TIER_3_FULL = "TIER_3_FULL"


class DeliveryStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    FAILED = "FAILED"
    SUPPRESSED = "SUPPRESSED"


class ScopeType(str, Enum):
    MANAGER = "MANAGER"
    LOCATION = "LOCATION"


class WindowKind(str, Enum):
    ROLLING_90D = "ROLLING_90D"
    CALENDAR_QUARTER = "CALENDAR_QUARTER"


class PackageStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    READY = "READY"
    SEALED = "SEALED"
    RELEASED = "RELEASED"


class CredibilityVariant(str, Enum):
    CORROBORATION_WEIGHTED = "CORROBORATION_WEIGHTED"
    RECENCY_WEIGHTED = "RECENCY_WEIGHTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true unless noted)
# ---------------------------------------------------------------------------

class Employee(TypedDict, total=False):
    id: str
    employee_number: str
    full_name: str
    email: str
    manager_id: Optional[str]
    location_code: str
    department: str
    employment_status: str
    hire_date: str
    created_at: str
    updated_at: str
    version: int


class Investigator(TypedDict, total=False):
    id: str
    employee_id: str
    certification_level: str
    max_active_cases: int
    active_case_count: int
    conflicted_employee_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class IntakeChannelConfig(TypedDict, total=False):
    id: str
    channel_code: str
    display_name: str
    default_category: str
    default_severity: str
    requires_reporter_identity: bool
    sla_business_days: int
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    case_number: str
    intake_channel_id: str
    reporter_employee_id: Optional[str]
    subject_employee_id: str
    category: str
    severity: str
    status: str
    assigned_investigator_id: Optional[str]
    litigation_hold: bool
    reopen_count: int
    sla_due_date: Optional[str]
    intake_received_at: str
    closed_at: Optional[str]
    days_to_close: Optional[int]
    overdue_business_days: int
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict, total=False):
    id: str
    case_id: str
    interviewee_employee_id: str
    interviewer_investigator_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    documentation_text: Optional[str]
    documentation_word_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    case_id: str
    submitted_by_employee_id: str
    evidence_type: str
    description: str
    custody_sequence: int
    status: str
    weight: Optional[float]
    reviewed_by_investigator_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CredibilityAssessment(TypedDict, total=False):
    id: str
    case_id: str
    subject_employee_id: str
    assessor_investigator_id: str
    corroboration_count: int
    contradiction_count: int
    account_age_days: int
    score_corroboration: float
    score_recency: float
    active_variant: str
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict, total=False):
    id: str
    case_id: str
    author_investigator_id: str
    substantiation_status: str
    approval_status: str
    rationale_text: str
    calibration_score: Optional[float]
    calibrated_by_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class RecommendedAction(TypedDict, total=False):
    id: str
    finding_id: str
    action_type: str
    severity_points: int
    justification: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosureNotice(TypedDict, total=False):
    id: str
    case_id: str
    closure_sequence: int
    recipient_employee_id: str
    recipient_role: str
    confidentiality_tier: str
    body_text: str
    sent_at: Optional[str]
    delivery_status: str
    created_at: str
    updated_at: str
    version: int


class TrendSnapshot(TypedDict, total=False):
    id: str
    scope_type: str
    scope_key: str
    window_kind: str
    as_of: str
    closed_case_count: int
    substantiated_count: int
    case_rate_per_100: float
    is_stale: bool
    created_at: str
    updated_at: str
    version: int


class LitigationFilePackage(TypedDict, total=False):
    id: str
    case_id: str
    assembled_by: str
    status: str
    manifest_hash: Optional[str]
    item_count: int
    sealed_at: Optional[str]
    package_version: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; carries ONLY id + created_at
class HolidayCalendarEntry(TypedDict, total=False):
    id: str
    holiday_date: str
    label: str
    created_at: str
