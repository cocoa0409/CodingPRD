"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REVIEW_COORDINATOR = "ReviewCoordinator"
    REVIEWER = "Reviewer"
    CHIEF_REVIEWER = "ChiefReviewer"
    APPLICANT = "Applicant"


class EngagementStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IN_PROGRESS = "IN_PROGRESS"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    COMMENTS_ISSUED = "COMMENTS_ISSUED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class CommentStatus(str, Enum):
    OPEN = "OPEN"
    ADDRESSED = "ADDRESSED"
    REOPENED = "REOPENED"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"


class DeferredStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    APPROVED = "APPROVED"


class RecordStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    TRANSMITTED = "TRANSMITTED"


class Jurisdiction(TypedDict, total=False):
    id: str
    state_code: str
    ibc_edition: str
    asce7_edition: str
    fee_method: str
    turnaround_days: int
    sla_mode: str
    free_resubmittal_cycles: int
    requires_se_seal: bool
    allows_deferred_submittals: bool
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict, total=False):
    id: str
    full_name: str
    licenses: List[Dict[str, Any]]
    max_concurrent_assignments: int
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    project_name: str
    jurisdiction_id: str
    applicant_contact_id: str
    reviewer_of_record_id: str
    building_type: str
    risk_category: str
    scope: str
    declared_valuation_cents: int
    floor_area_sqft: int
    requested_expedite: bool
    pinned_state_code: str
    pinned_ibc_edition: str
    pinned_asce7_edition: str
    pinned_fee_method: str
    pinned_turnaround_days: int
    pinned_sla_mode: str
    pinned_free_resubmittal_cycles: int
    pinned_requires_se_seal: bool
    pinned_allows_deferred_submittals: bool
    estimated_fee_cents: int
    final_fee_cents: Optional[int]
    cycle_count: int
    unresolved_comment_count: int
    deferred_pending_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewCycle(TypedDict, total=False):
    id: str
    engagement_id: str
    cycle_number: int
    documents_ref: str
    received_at: str
    due_at: str
    completed_at: Optional[str]
    is_on_time: Optional[bool]
    load_path_confirmed: bool
    lateral_system_confirmed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewAssignment(TypedDict, total=False):
    id: str
    cycle_id: str
    reviewer_id: str
    assigned_at: str
    ended_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeficiencyComment(TypedDict, total=False):
    id: str
    engagement_id: str
    raised_in_cycle_id: str
    raised_by_reviewer_id: str
    code_section_ref: str
    reference_edition: str
    severity: str
    category: str
    comment_text: str
    response_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable ledger entry (PRD §2.5): carries ONLY id + created_at — no
# updated_at, no version.
class CommentResponse(TypedDict, total=False):
    id: str
    comment_id: str
    responder_contact_id: str
    response_text: str
    created_at: str


class DeferredSubmittal(TypedDict, total=False):
    id: str
    engagement_id: str
    item_type: str
    description: str
    documents_ref: Optional[str]
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewRecord(TypedDict, total=False):
    id: str
    engagement_id: str
    record_number: str
    pinned_ibc_edition: str
    pinned_asce7_edition: str
    cycle_count_snapshot: int
    sealed_by_reviewer_id: Optional[str]
    sealed_at: Optional[str]
    transmitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
