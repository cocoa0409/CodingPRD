"""Domain types for the conference program committee API: status enums,
entity TypedDicts and the role enum, all named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────


class UserRole(str, Enum):
    CONFERENCE_ADMIN = "ConferenceAdmin"
    PROGRAM_CHAIR = "ProgramChair"
    REVIEWER = "Reviewer"
    AUTHOR = "Author"
    PRESS_OFFICER = "PressOfficer"


# ─── Status enums ─────────────────────────────────────────────────────────


class ConferenceStatus(str, Enum):
    DRAFT = "DRAFT"
    CFA_OPEN = "CFA_OPEN"
    CFA_CLOSED = "CFA_CLOSED"
    REVIEW_OPEN = "REVIEW_OPEN"
    REVIEW_CLOSED = "REVIEW_CLOSED"
    DECISIONS_RELEASED = "DECISIONS_RELEASED"
    PROGRAM_PUBLISHED = "PROGRAM_PUBLISHED"


class AuthorSanctionStatus(str, Enum):
    NONE = "NONE"
    WARNED = "WARNED"
    BARRED = "BARRED"


class AbstractStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SCORED = "SCORED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"
    WAITLISTED = "WAITLISTED"
    REJECTED = "REJECTED"
    CONFIRMED = "CONFIRMED"
    SCHEDULED = "SCHEDULED"
    PRESENTED = "PRESENTED"
    NO_SHOW = "NO_SHOW"
    WITHDRAWN = "WITHDRAWN"


class EmbargoStatus(str, Enum):
    NONE = "NONE"
    EMBARGOED = "EMBARGOED"
    RELEASED = "RELEASED"
    BREACHED = "BREACHED"


class PresentationFormat(str, Enum):
    ORAL = "ORAL"
    POSTER = "POSTER"
    WORKSHOP = "WORKSHOP"


class AbstractDecision(str, Enum):
    ORAL = "ORAL"
    POSTER = "POSTER"
    WORKSHOP = "WORKSHOP"
    REJECTED = "REJECTED"


class MemberRole(str, Enum):
    REVIEWER = "REVIEWER"
    CHAIR = "CHAIR"


class CommitteeMemberStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RESIGNED = "RESIGNED"


class CoiDeclarationStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"


class ConflictSubjectType(str, Enum):
    AUTHOR_EMAIL = "AUTHOR_EMAIL"
    AFFILIATION = "AFFILIATION"
    NONE = "NONE"


class ConflictType(str, Enum):
    COAUTHOR = "COAUTHOR"
    INSTITUTIONAL = "INSTITUTIONAL"
    FINANCIAL = "FINANCIAL"
    ADVISORY = "ADVISORY"
    NONE = "NONE"


class ReviewStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    SUBMITTED = "SUBMITTED"
    DECLINED = "DECLINED"
    VOIDED = "VOIDED"


class ReviewConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DiscrepancyCaseStatus(str, Enum):
    OPEN = "OPEN"
    ARBITER_ASSIGNED = "ARBITER_ASSIGNED"
    THIRD_REVIEW_PENDING = "THIRD_REVIEW_PENDING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class ResolutionMethod(str, Enum):
    THIRD_REVIEW = "THIRD_REVIEW"
    CHAIR_OVERRIDE = "CHAIR_OVERRIDE"


class SessionStatus(str, Enum):
    PLANNED = "PLANNED"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class AccreditationPosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class SessionSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PRESENTED = "PRESENTED"
    NO_SHOW_RECORDED = "NO_SHOW_RECORDED"
    WITHDRAWN = "WITHDRAWN"
    MOVED = "MOVED"


class AccreditationValidationStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class DisclosureStatementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"


class ChangeType(str, Enum):
    MOVE = "MOVE"
    SWAP = "SWAP"
    SUBSTITUTE_PRESENTER = "SUBSTITUTE_PRESENTER"
    WITHDRAW = "WITHDRAW"


class ChangeRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Every entity below carries id, created_at, updated_at and version, EXCEPT
# ConflictDeclaration, which the PRD declares append-only: it carries only
# id and created_at.


class Conference(TypedDict):
    id: str
    name: str
    code: str
    status: str
    event_start_utc: str
    event_end_utc: str
    abstract_deadline_utc: str
    review_deadline_utc: str
    program_freeze_utc: str
    oral_slot_capacity: int
    poster_slot_capacity: int
    workshop_slot_capacity: int
    accepted_oral_count: int
    accepted_poster_count: int
    accepted_workshop_count: int
    waitlisted_count: int
    cme_minutes_pool_total: int
    cme_minutes_allocated: int
    cme_minutes_available: int
    cfa_extension_count: int
    review_reopen_count: int
    abstract_sequence: int
    created_at: str
    updated_at: str
    version: int


class SubmissionCategory(TypedDict):
    id: str
    conference_id: str
    code: str
    name: str
    max_word_count: int
    requires_structured_body: bool
    allowed_formats: List[str]
    min_reviews_required: int
    discrepancy_threshold: float
    cme_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Author(TypedDict):
    id: str
    full_name: str
    email: str
    affiliation: str
    is_registered: bool
    registered_at: Optional[str]
    no_show_strikes: int
    embargo_breach_count: int
    sanction_status: str
    created_at: str
    updated_at: str
    version: int


class Abstract(TypedDict):
    id: str
    conference_id: str
    category_id: str
    submitting_author_id: str
    title: str
    body_word_count: int
    body_structured: bool
    requested_format: str
    keywords: List[str]
    coauthor_emails: List[str]
    is_newsworthy: bool
    blind_code: str
    status: str
    revision_round: int
    submitted_review_count: int
    provisional_score: Optional[float]
    final_score: Optional[float]
    score_spread: Optional[float]
    decision: Optional[str]
    decision_downgraded: bool
    decided_by_member_id: Optional[str]
    embargo_status: str
    embargo_until_utc: Optional[str]
    press_outlet_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeMember(TypedDict):
    id: str
    conference_id: str
    full_name: str
    email: str
    expertise_keywords: List[str]
    member_role: str
    max_review_load: int
    current_review_load: int
    calibration_bias: float
    status: str
    coi_declaration_status: str
    chaired_session_count: int
    created_at: str
    updated_at: str
    version: int


class ConflictDeclaration(TypedDict):
    """Append-only declaration: carries only id and created_at as common fields."""

    id: str
    member_id: str
    conflict_subject_type: str
    conflict_subject_value: Optional[str]
    conflict_type: str
    declared_at: str
    created_at: str


class Review(TypedDict):
    id: str
    abstract_id: str
    reviewer_member_id: str
    status: str
    assigned_round: int
    expertise_match_score: Optional[float]
    due_utc: str
    is_third_review: bool
    score_originality: Optional[int]
    score_methodology: Optional[int]
    score_relevance: Optional[int]
    score_clarity: Optional[int]
    confidence: Optional[str]
    recommended_format: Optional[str]
    comments_to_authors: Optional[str]
    weighted_score: Optional[float]
    submitted_at: Optional[str]
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiscrepancyCase(TypedDict):
    id: str
    abstract_id: str
    arbiter_member_id: Optional[str]
    third_review_id: Optional[str]
    status: str
    spread_at_open: Optional[float]
    resolution_method: Optional[str]
    resolved_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    conference_id: str
    chair_member_id: str
    theme_code: str
    format: str
    room_code: str
    start_utc: str
    end_utc: str
    capacity_slots: int
    cme_designated: bool
    status: str
    slot_count: int
    committed_minutes: int
    accredited_credit_total: float
    accreditation_posture: str
    created_at: str
    updated_at: str
    version: int


class SessionSlot(TypedDict):
    id: str
    session_id: str
    abstract_id: str
    presenter_author_id: str
    swapped_with_slot_id: Optional[str]
    position: int
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CmeAccreditation(TypedDict):
    id: str
    abstract_id: str
    content_minutes: int
    commercial_support_disclosed: bool
    commercial_bias_flag: bool
    awarded_credits: float
    validation_status: str
    validated_by_member_id: Optional[str]
    validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureStatement(TypedDict):
    id: str
    abstract_id: str
    accreditation_id: str
    author_id: str
    has_financial_relationship: bool
    relationship_entity: Optional[str]
    mitigation_required: bool
    mitigation_completed: bool
    status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramChangeRequest(TypedDict):
    id: str
    conference_id: str
    session_slot_id: str
    requested_by_author_id: Optional[str]
    change_type: str
    target_session_id: Optional[str]
    substitute_presenter_author_id: Optional[str]
    approver_member_id: Optional[str]
    status: str
    submitted_at: str
    days_to_event: Optional[int]
    estimated_fee_cents: int
    final_fee_cents: Optional[int]
    rush_pct_applied: Optional[float]
    created_at: str
    updated_at: str
    version: int
