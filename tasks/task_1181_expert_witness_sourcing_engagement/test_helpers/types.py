"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class RosterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    REMOVED = "REMOVED"


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    SOURCING = "SOURCING"
    ENGAGED = "ENGAGED"
    DISCOVERY = "DISCOVERY"
    TRIAL_PREP = "TRIAL_PREP"
    CLOSED = "CLOSED"


class EngagementRequestStatus(str, Enum):
    OPEN = "OPEN"
    SCREENING = "SCREENING"
    READY = "READY"
    FILLED = "FILLED"


class ConflictCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"
    WAIVED = "WAIVED"


class CredentialReviewStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    PASSED_WITH_CONDITIONS = "PASSED_WITH_CONDITIONS"


class EngagementStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    NEGOTIATING = "NEGOTIATING"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class PrivilegeTier(str, Enum):
    DISCOVERABLE = "DISCOVERABLE"
    WORK_PRODUCT = "WORK_PRODUCT"
    PRIVILEGED = "PRIVILEGED"


class DocumentProductionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RECALLED = "RECALLED"


class ReportType(str, Enum):
    LIABILITY = "LIABILITY"
    DAMAGES = "DAMAGES"
    REBUTTAL = "REBUTTAL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    FINALIZED = "FINALIZED"
    DISCLOSED = "DISCLOSED"
    WITHDRAWN = "WITHDRAWN"


class ScheduleKind(str, Enum):
    DEPOSITION = "DEPOSITION"
    TRIAL = "TRIAL"


class ScheduleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LineItemKind(str, Enum):
    PREP = "PREP"
    TESTIMONY = "TESTIMONY"
    TRAVEL_TIME = "TRAVEL_TIME"


class InvoiceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CASE_MANAGER = "CaseManager"
    CONFLICT_ANALYST = "ConflictAnalyst"
    CREDENTIAL_ANALYST = "CredentialAnalyst"
    BILLING_REVIEWER = "BillingReviewer"
    EXPERT = "Expert"


class Expert(TypedDict, total=False):
    id: str
    full_name: str
    specialty_area: str
    roster_status: str
    daubert_challenge_count: int
    daubert_exclusion_count: int
    max_concurrent_engagements: int
    active_engagement_count: int
    evaluation_count: int
    rating_simple: float
    rating_decayed: float
    created_at: str
    updated_at: str
    version: int


class Case(TypedDict, total=False):
    id: str
    case_number: str
    court: str
    title: str
    budget_cents: int
    trial_date: str
    report_deadline: str
    status: str
    actuals_paid_cents: int
    committed_cents: int
    approved_outstanding_cents: int
    created_at: str
    updated_at: str
    version: int


class EngagementRequest(TypedDict, total=False):
    id: str
    case_id: str
    specialty_area: str
    notes: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConflictCheck(TypedDict, total=False):
    id: str
    engagement_request_id: str
    expert_id: str
    adverse_parties: List[str]
    status: str
    resolution_rationale: str
    created_at: str
    updated_at: str
    version: int


class CredentialReview(TypedDict, total=False):
    id: str
    engagement_request_id: str
    expert_id: str
    status: str
    daubert_notes: str
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    engagement_request_id: str
    case_id: str
    expert_id: str
    status: str
    hourly_rate_cents: int
    retainer_cents: int
    expense_cap_cents: int
    negotiation_round_count: int
    nda_executed: bool
    retainer_funded_cents: int
    retainer_drawn_cents: int
    retainer_refunded_cents: int
    retainer_remaining_cents: int
    expenses_approved_cents: int
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class DocumentProduction(TypedDict, total=False):
    id: str
    engagement_id: str
    title: str
    privilege_tier: str
    content_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Report(TypedDict, total=False):
    id: str
    engagement_id: str
    title: str
    report_type: str
    deadline_at: str
    status: str
    revision_count: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    name: str
    location: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class TestimonySchedule(TypedDict, total=False):
    id: str
    engagement_id: str
    venue_id: Optional[str]
    kind: str
    start_at: str
    end_at: str
    estimated_hours: float
    travel_required: bool
    actual_hours: float
    cancellation_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    engagement_id: str
    period_start: str
    period_end: str
    line_items: List[Any]
    travel_expense_cents: int
    total_cents: int
    computed_total_cents: int
    status: str
    dispute_count: int
    retainer_draw_cents: int
    billed_to_client_cents: int
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict, total=False):
    """Immutable record: carries only id + created_at (no updated_at, no version)."""
    id: str
    engagement_id: str
    expert_id: str
    overall_score: float
    quality_score: Optional[float]
    timeliness_score: Optional[float]
    testimony_score: Optional[float]
    comments: str
    evaluated_at: str
    created_at: str
