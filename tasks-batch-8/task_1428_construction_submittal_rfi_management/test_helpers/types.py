"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ───────────────────────────────────────────────


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROJECT_MANAGER = "ProjectManager"
    PROJECT_ENGINEER = "ProjectEngineer"
    REVIEWER = "Reviewer"
    SUBCONTRACTOR_REP = "SubcontractorRep"
    OWNER_REP = "OwnerRep"


# ─── Enumerated statuses (PRD §3) ───────────────────────────────────


class ProjectPosture(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSEOUT = "CLOSEOUT"
    CLOSED = "CLOSED"


class SpecSectionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"


class SubcontractorStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class Discipline(str, Enum):
    ARCH = "ARCH"
    STRUCT = "STRUCT"
    MEP = "MEP"
    CIVIL = "CIVIL"


class ReviewerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class SubmittalKind(str, Enum):
    PRODUCT_DATA = "PRODUCT_DATA"
    SHOP_DRAWINGS = "SHOP_DRAWINGS"
    SAMPLES = "SAMPLES"
    MOCKUP = "MOCKUP"
    CERTIFICATES = "CERTIFICATES"
    O_AND_M_MANUALS = "O_AND_M_MANUALS"


class ReviewStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IN_REVIEW = "IN_REVIEW"
    RETURNED_NEEDS_RESUBMIT = "RETURNED_NEEDS_RESUBMIT"
    APPROVED = "APPROVED"
    RELEASED = "RELEASED"
    DISTRIBUTED = "DISTRIBUTED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class ExpeditingStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    MONITORING = "MONITORING"
    EXPEDITING = "EXPEDITING"
    ESCALATED = "ESCALATED"
    CLEAR = "CLEAR"


class DeferralStatus(str, Enum):
    NONE = "NONE"
    DEFERRAL_REQUESTED = "DEFERRAL_REQUESTED"
    DEFERRED_APPROVED = "DEFERRED_APPROVED"


class RevisionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"


class ActionCode(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class LongLeadItemStatus(str, Enum):
    IDENTIFIED = "IDENTIFIED"
    QUOTED = "QUOTED"
    PO_ISSUED = "PO_ISSUED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class Criticality(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    STANDARD = "STANDARD"


class RfiStatus(str, Enum):
    OPEN = "OPEN"
    ROUTED = "ROUTED"
    ANSWERED = "ANSWERED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class RfiPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AssessmentStatus(str, Enum):
    ESTIMATED = "ESTIMATED"
    PRICED = "PRICED"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"


class DistributionStatus(str, Enum):
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class DistributionSourceType(str, Enum):
    RFI = "RFI"
    SUBMITTAL = "SUBMITTAL"


class ActivityStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class EscalationEventType(str, Enum):
    RFI_OVERDUE = "RFI_OVERDUE"
    LLI_ESCALATION_RAISED = "LLI_ESCALATION_RAISED"
    LLI_ESCALATION_CLEARED = "LLI_ESCALATION_CLEARED"
    DIST_ACK_OVERDUE = "DIST_ACK_OVERDUE"
    SUBCONTRACTOR_WATCH = "SUBCONTRACTOR_WATCH"
    SUBCONTRACTOR_SUSPENDED = "SUBCONTRACTOR_SUSPENDED"


# ─── Entity TypedDicts (PRD §2.4 common fields) ─────────────────────
# Twelve primary resources carry id + created_at + updated_at + version.


class Project(TypedDict, total=False):
    id: str
    project_name: str
    contract_start_date: Optional[str]
    rfi_response_days: int
    ack_required_days: int
    mobilization_buffer_days: int
    long_lead_threshold_days: int
    expedite_window_days: int
    holiday_dates: List[str]
    initial_contingency_cents: int
    contingency_reserved_cents: int
    contingency_spent_cents: int
    contingency_available_cents: int
    gc_tier_threshold_cents: int
    ops_scan_index: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class SpecSection(TypedDict, total=False):
    id: str
    project_id: str
    section_number: str
    title: str
    lead_time_days: int
    review_days: int
    required_discipline: str
    default_need_date: Optional[str]
    responsible_subcontractor_id: Optional[str]
    required_submittal_kinds: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Subcontractor(TypedDict, total=False):
    id: str
    project_id: str
    company_name: str
    trade: str
    contact_email: str
    late_ack_count: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict, total=False):
    id: str
    project_id: str
    display_name: str
    discipline: str
    review_capacity: int
    open_review_count: int
    reviewer_status: str
    created_at: str
    updated_at: str
    version: int


class Submittal(TypedDict, total=False):
    id: str
    project_id: str
    spec_section_id: str
    submittal_kind: str
    item_number: str
    required_on_site_date: Optional[str]
    required_approval_date: Optional[str]
    required_submission_date: Optional[str]
    is_long_lead: bool
    review_status: str
    expediting_status: str
    deferral_status: str
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class SubmittalRevision(TypedDict, total=False):
    id: str
    submittal_id: str
    revision_number: int
    document_ref: str
    notes: str
    status: str
    action_code: Optional[str]
    reviewer_id: Optional[str]
    submitted_date: str
    routed_date: Optional[str]
    review_due_date: Optional[str]
    returned_date: Optional[str]
    is_late_return: bool
    return_comments: str
    created_at: str
    updated_at: str
    version: int


class LongLeadItem(TypedDict, total=False):
    id: str
    project_id: str
    submittal_id: str
    description: str
    criticality: str
    status: str
    required_on_site_date: Optional[str]
    days_late: int
    escalation_level: int
    priority_score: int
    quoted_date: Optional[str]
    po_issued_date: Optional[str]
    shipped_date: Optional[str]
    delivered_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RFI(TypedDict, total=False):
    id: str
    project_id: str
    rfi_number: str
    subject: str
    question_text: str
    spec_section_id: Optional[str]
    submittal_id: Optional[str]
    priority: str
    required_discipline: str
    status: str
    cycle_count: int
    opened_date: str
    due_date: str
    is_overdue: bool
    routed_reviewer_id: Optional[str]
    routed_date: Optional[str]
    answer_text: Optional[str]
    answered_date: Optional[str]
    answered_by_reviewer_id: Optional[str]
    is_late_answer: bool
    cost_impact_flag: bool
    schedule_impact_flag: bool
    estimated_schedule_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ImpactAssessment(TypedDict, total=False):
    id: str
    project_id: str
    rfi_id: str
    status: str
    estimated_cost_cents: int
    provisional_delta_cents: int
    sub_quote_cents: Optional[int]
    gc_markup_tier: Optional[int]
    final_delta_cents: Optional[int]
    priced_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    price_cycle: int
    created_at: str
    updated_at: str
    version: int


class DistributionRecord(TypedDict, total=False):
    id: str
    project_id: str
    subcontractor_id: str
    source_type: str
    source_id: str
    status: str
    sent_date: Optional[str]
    ack_due_date: Optional[str]
    acknowledged_date: Optional[str]
    is_overdue: bool
    created_at: str
    updated_at: str
    version: int


class InstallationActivity(TypedDict, total=False):
    id: str
    project_id: str
    submittal_id: str
    subcontractor_id: str
    description: str
    start_date: str
    end_date: str
    status: str
    shift_applied_days: int
    created_at: str
    updated_at: str
    version: int


class OwnerReport(TypedDict, total=False):
    id: str
    project_id: str
    period_start: str
    period_end: str
    status: str
    published_at: Optional[str]
    snapshot_metrics: Optional[dict]
    superseded_by_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscalationEvent(TypedDict, total=False):
    """Append-only log entry (PRD §2.4): only id + created_at, never updated."""

    id: str
    project_id: str
    event_type: str
    source_type: str
    source_id: str
    detail: str
    event_date: str
    created_at: str
