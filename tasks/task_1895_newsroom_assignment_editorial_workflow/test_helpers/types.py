"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource descriptions. Resources described as
carrying the standard system-managed fields (`id`, `created_at`,
`updated_at`, `version`) include all four; `ReviewRecord` and
`AnalyticsReport` are immutable measurements that carry only `id` and
`created_at` (both `updated_at` and `version` are absent from their
representations).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    REPORTER = "Reporter"
    PHOTOGRAPHER = "Photographer"
    COPY_EDITOR = "CopyEditor"
    FACT_CHECKER = "FactChecker"
    LEGAL_REVIEWER = "LegalReviewer"
    ASSIGNMENT_EDITOR = "AssignmentEditor"
    MANAGING_EDITOR = "ManagingEditor"
    NEWS_DIRECTOR = "NewsDirector"
    ANALYTICS_PRODUCER = "AnalyticsProducer"


class RoleCapability(str, Enum):
    REPORTER = "REPORTER"
    PHOTOGRAPHER = "PHOTOGRAPHER"
    COPY_EDITOR = "COPY_EDITOR"
    FACT_CHECKER = "FACT_CHECKER"
    LEGAL_REVIEWER = "LEGAL_REVIEWER"
    DESK_EDITOR = "DESK_EDITOR"
    MANAGING_EDITOR = "MANAGING_EDITOR"
    NEWS_DIRECTOR = "NEWS_DIRECTOR"
    ANALYST = "ANALYST"


class Desk(str, Enum):
    METRO = "METRO"
    BUSINESS = "BUSINESS"
    SPORTS = "SPORTS"
    FEATURES = "FEATURES"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class PitchStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DESK_REVIEW = "DESK_REVIEW"
    GREENLIT = "GREENLIT"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class PitchUrgency(str, Enum):
    STANDARD = "STANDARD"
    URGENT = "URGENT"
    BREAKING = "BREAKING"


class StoryStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_EDIT = "IN_EDIT"
    FACT_CHECK = "FACT_CHECK"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    CLEARED = "CLEARED"
    SCHEDULED = "SCHEDULED"
    ON_HOLD = "ON_HOLD"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"
    KILLED = "KILLED"


class StoryType(str, Enum):
    PRINT = "PRINT"
    DIGITAL = "DIGITAL"
    BROADCAST = "BROADCAST"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    BUMPED = "BUMPED"


class AssignmentRole(str, Enum):
    REPORTER = "REPORTER"
    PHOTOGRAPHER = "PHOTOGRAPHER"


class SlotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class ReviewType(str, Enum):
    FACT_CHECK = "FACT_CHECK"
    LEGAL = "LEGAL"


class ReviewVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CorrectionSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    RETRACTION = "RETRACTION"


class CorrectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    ISSUED = "ISSUED"


class AnalyticsVariant(str, Enum):
    REALTIME = "REALTIME"
    SETTLED = "SETTLED"


class AnalyticsReportStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class AnalyticsTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class BreakingEventStatus(str, Enum):
    DECLARED = "DECLARED"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class CallInStatus(str, Enum):
    PAGED = "PAGED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class StaffMember(TypedDict, total=False):
    id: str
    full_name: str
    role_capability: str
    home_desk: str
    employment_status: str
    max_concurrent_assignments: int
    hourly_rate_cents: int
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Pitch(TypedDict, total=False):
    id: str
    title: str
    summary: str
    desk: str
    urgency: str
    deadline_at: str
    submitting_staff_id: str
    status: str
    rework_round: int
    greenlit_story_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Story(TypedDict, total=False):
    id: str
    pitch_id: str
    desk: str
    story_type: str
    author_staff_id: str
    status: str
    word_count: int
    embargo_until: Optional[str]
    slot_id: Optional[str]
    priority_score: float
    correction_count: int
    published_at: Optional[str]
    superseded_by_story_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    story_id: str
    staff_id: str
    assignment_role: str
    status: str
    start_at: str
    end_at: str
    planned_effort_minutes: int
    actual_effort_minutes: Optional[int]
    provisional_cost_cents: int
    final_cost_cents: Optional[int]
    completed_at: Optional[str]
    bumped_by_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublicationSlot(TypedDict, total=False):
    id: str
    channel: str
    window_start: str
    window_end: str
    capacity: int
    reserved_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable measurement: carries only id + created_at (no updated_at/version)
class ReviewRecord(TypedDict, total=False):
    id: str
    story_id: str
    reviewer_staff_id: str
    review_type: str
    verdict: str
    notes: Optional[str]
    reviewed_story_version: int
    review_round: int
    is_current: bool
    created_at: str


class Correction(TypedDict, total=False):
    id: str
    story_id: str
    proposer_staff_id: str
    severity: str
    correction_text: str
    status: str
    approver_staff_id: Optional[str]
    correction_number: Optional[int]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable measurement: carries only id + created_at (no updated_at/version)
class AnalyticsReport(TypedDict, total=False):
    id: str
    story_id: str
    variant: str
    window_start: str
    window_end: str
    views: int
    engagement_minutes: int
    raw_score: float
    tier: str
    performance_score: float
    status: str
    created_at: str


class BreakingNewsEvent(TypedDict, total=False):
    id: str
    title: str
    priority_band: int
    window_start: str
    window_end: str
    call_in_pool_size: int
    status: str
    declared_by: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffCallIn(TypedDict, total=False):
    id: str
    event_id: str
    staff_id: str
    status: str
    paged_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int
