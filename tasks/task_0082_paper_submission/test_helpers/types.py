"""Domain types for the Paper Submission API.

Entity TypedDicts, status enums, and role enum derived from PRD §2.4
(common resource properties) and §3 (per-entity lifecycles).

PRD §2.4 — Two entities (PlagiarismCheck, AuditLog) are write-once event
records carrying only id and created_at; all other entities carry the
full envelope (id + created_at + updated_at + version).
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    AUTHOR = "Author"
    EDITOR_IN_CHIEF = "EditorInChief"
    SECTION_EDITOR = "SectionEditor"
    ASSOCIATE_EDITOR = "AssociateEditor"
    REVIEWER = "Reviewer"


# ---------------------------------------------------------------------------
# Editor seat enum (PRD §3.4) — distinct from the role-header values
# ---------------------------------------------------------------------------
class EditorRole(str, Enum):
    EDITOR_IN_CHIEF = "EDITOR_IN_CHIEF"
    SECTION_EDITOR = "SECTION_EDITOR"
    ASSOCIATE_EDITOR = "ASSOCIATE_EDITOR"


# ---------------------------------------------------------------------------
# Reviewer pool status (PRD §3.5 — pool entry lifecycle)
# ---------------------------------------------------------------------------
class ReviewerPoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# Manuscript status (PRD §3.2-§3.9)
# ---------------------------------------------------------------------------
class ManuscriptStatus(str, Enum):
    DRAFT = "DRAFT"
    AWAITING_COAUTHOR = "AWAITING_COAUTHOR"
    SUBMITTED = "SUBMITTED"
    DESK_REJECTED = "DESK_REJECTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    REVISION_SUBMITTED = "REVISION_SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    IN_PRODUCTION = "IN_PRODUCTION"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


# ---------------------------------------------------------------------------
# Review modes (PRD §3.2)
# ---------------------------------------------------------------------------
class ReviewMode(str, Enum):
    SINGLE_BLIND = "SINGLE_BLIND"
    DOUBLE_BLIND = "DOUBLE_BLIND"
    OPEN = "OPEN"


# ---------------------------------------------------------------------------
# CoAuthorConfirmation status (PRD §3.2)
# ---------------------------------------------------------------------------
class CoAuthorConfirmationStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"


# ---------------------------------------------------------------------------
# PlagiarismCheck result (PRD §3.3)
# ---------------------------------------------------------------------------
class PlagiarismResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


# ---------------------------------------------------------------------------
# ReviewerInvitation status (PRD §3.5)
# ---------------------------------------------------------------------------
class ReviewerInvitationStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Review status (PRD §3.6)
# ---------------------------------------------------------------------------
class ReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Reviewer recommendation values (PRD §3.6)
# ---------------------------------------------------------------------------
class ReviewerRecommendation(str, Enum):
    ACCEPT = "ACCEPT"
    MINOR_REVISION = "MINOR_REVISION"
    MAJOR_REVISION = "MAJOR_REVISION"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# EditorDecision recommendation_from_associate and final_decision (PRD §3.7)
# ---------------------------------------------------------------------------
class EditorRecommendation(str, Enum):
    ACCEPT = "ACCEPT"
    MINOR_REVISION = "MINOR_REVISION"
    MAJOR_REVISION = "MAJOR_REVISION"
    REJECT = "REJECT"
    TRANSFER = "TRANSFER"


# ---------------------------------------------------------------------------
# EditorDecision lifecycle (PRD §3.7)
# ---------------------------------------------------------------------------
class EditorDecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    RECOMMENDED = "RECOMMENDED"
    FINALIZED = "FINALIZED"


# ---------------------------------------------------------------------------
# Publication status (PRD §3.9)
# ---------------------------------------------------------------------------
class PublicationStatus(str, Enum):
    COPY_EDITING = "COPY_EDITING"
    PROOF_REVIEW = "PROOF_REVIEW"
    ONLINE_FIRST = "ONLINE_FIRST"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


# ---------------------------------------------------------------------------
# Indexing target (PRD §3.9)
# ---------------------------------------------------------------------------
class IndexingTarget(str, Enum):
    PUBMED = "PUBMED"
    WEB_OF_SCIENCE = "WEB_OF_SCIENCE"
    SCOPUS = "SCOPUS"


# ---------------------------------------------------------------------------
# Indexing acknowledgement status (PRD §3.9)
# ---------------------------------------------------------------------------
class IndexingAckStatus(str, Enum):
    PENDING = "PENDING"
    ACK = "ACK"
    FAILED = "FAILED"


# ===========================================================================
# Entity TypedDicts
# PRD §2.4: Author, Reviewer, Editor, Manuscript, CoAuthorConfirmation,
#           ReviewerInvitation, Review, EditorDecision, Publication carry
#           id + created_at + updated_at + version.
#           PlagiarismCheck and AuditLog are append-only — only id + created_at.
# ===========================================================================
class Author(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    orcid_id: Optional[str]
    orcid_verified: bool
    institution: str
    recent_collaborator_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    institution: str
    expertise_tags: List[str]
    recent_collaborator_ids: List[str]
    active_assignments: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Editor(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    institution: str
    role: str
    topic_tags: List[str]
    recent_collaborator_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Manuscript(TypedDict, total=False):
    id: str
    title: str
    corresponding_author_id: str
    co_author_ids: List[str]
    topic_tag: str
    review_mode: str
    manuscript_file_uri: str
    supplementary_file_uris: List[str]
    declaration_coi: str
    declaration_funding: str
    declaration_ethics: str
    suggested_reviewer_ids: List[str]
    excluded_reviewer_ids: List[str]
    status: str
    section_editor_id: Optional[str]
    associate_editor_id: Optional[str]
    associate_assigned_at: Optional[str]
    associate_window_end_at: Optional[str]
    revision_round: int
    revision_deadline_at: Optional[str]
    plagiarism_similarity: Optional[float]
    doi: Optional[str]
    issue_label: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoAuthorConfirmation(TypedDict, total=False):
    id: str
    manuscript_id: str
    author_id: str
    status: str
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: PlagiarismCheck — append-only, NO updated_at / version
class PlagiarismCheck(TypedDict, total=False):
    id: str
    manuscript_id: str
    revision_round: int
    similarity_percent: float
    report_uri: str
    result: str
    created_at: str


class ReviewerInvitation(TypedDict, total=False):
    id: str
    manuscript_id: str
    reviewer_id: str
    revision_round: int
    response_deadline_at: str
    status: str
    coi_score: int
    match_score: int
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict, total=False):
    id: str
    invitation_id: str
    manuscript_id: str
    revision_round: int
    rating: Optional[int]
    recommendation: Optional[str]
    comments_to_author: Optional[str]
    comments_to_editor: Optional[str]
    status: str
    submitted_at: Optional[str]
    review_deadline_at: str
    created_at: str
    updated_at: str
    version: int


class EditorDecision(TypedDict, total=False):
    id: str
    manuscript_id: str
    revision_round: int
    recommendation_from_associate: str
    aggregate_score: Optional[float]
    aggregated_category: Optional[str]
    final_decision: Optional[str]
    decision_letter_body: Optional[str]
    compiled_reviewer_comments: Optional[str]
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Publication(TypedDict, total=False):
    id: str
    manuscript_id: str
    copy_edit_uri: str
    proof_uri: str
    doi: Optional[str]
    issue_label: str
    indexing_targets: List[str]
    indexing_status: dict
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# PRD §2.4 + §2.10: AuditLog — append-only, NO updated_at / version
class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    entity: str
    entity_id: str
    action: str
    from_state: Optional[str]
    to_state: Optional[str]
    details: dict
    created_at: str


__all__ = [
    "UserRole",
    "EditorRole",
    "ReviewerPoolStatus",
    "ManuscriptStatus",
    "ReviewMode",
    "CoAuthorConfirmationStatus",
    "PlagiarismResult",
    "ReviewerInvitationStatus",
    "ReviewStatus",
    "ReviewerRecommendation",
    "EditorRecommendation",
    "EditorDecisionStatus",
    "PublicationStatus",
    "IndexingTarget",
    "IndexingAckStatus",
    "Author",
    "Reviewer",
    "Editor",
    "Manuscript",
    "CoAuthorConfirmation",
    "PlagiarismCheck",
    "ReviewerInvitation",
    "Review",
    "EditorDecision",
    "Publication",
    "AuditLog",
]
