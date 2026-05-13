"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly (PRD §2.12 enumerations, §2.4 common
fields). Entities that PRD §2.4 declares as carrying only id+created_at
(DesignCategory, ReviewerPool, AuditEvent) omit updated_at/version from
their TypedDicts so downstream assertions never demand fields the
implementer is correctly told not to return.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_OPS = "PlatformOps"
    CLIENT = "Client"
    DESIGNER = "Designer"
    REVIEWER = "Reviewer"


# ---------------------------------------------------------------------------
# Status enums (PRD §2.12)
# ---------------------------------------------------------------------------
class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClientTaxJurisdiction(str, Enum):
    RESIDENT = "RESIDENT"
    NON_RESIDENT = "NON_RESIDENT"


class DesignerQualificationLevel(str, Enum):
    NOVICE = "NOVICE"
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    EXPERT = "EXPERT"


class DesignerTaxResidency(str, Enum):
    RESIDENT = "RESIDENT"
    NON_RESIDENT = "NON_RESIDENT"


class DesignerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_PLATFORM_REVIEW = "UNDER_PLATFORM_REVIEW"
    ON_SHELF = "ON_SHELF"
    IN_PRELIMINARY = "IN_PRELIMINARY"
    IN_SEMIFINAL = "IN_SEMIFINAL"
    IN_FINAL = "IN_FINAL"
    AWARDED = "AWARDED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ReviewStageKind(str, Enum):
    PRELIMINARY = "PRELIMINARY"
    SEMIFINAL = "SEMIFINAL"
    FINAL = "FINAL"


class ReviewStageStatus(str, Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    AGGREGATING = "AGGREGATING"
    PUBLISHED = "PUBLISHED"
    EXPIRED = "EXPIRED"


class SubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENING = "SCREENING"
    SCREEN_REJECTED = "SCREEN_REJECTED"
    ACCEPTED = "ACCEPTED"
    ADVANCING_SEMIFINAL = "ADVANCING_SEMIFINAL"
    ADVANCING_FINAL = "ADVANCING_FINAL"
    WINNER = "WINNER"
    RUNNER_UP = "RUNNER_UP"
    ELIMINATED = "ELIMINATED"
    WITHDRAWN = "WITHDRAWN"


class OriginalityVariant(str, Enum):
    PRELIMINARY_SCAN = "PRELIMINARY_SCAN"
    FINAL_CROSSCHECK = "FINAL_CROSSCHECK"


class ReviewAssignmentStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class DisputeType(str, Enum):
    PLAGIARISM = "PLAGIARISM"
    SCORING_FAIRNESS = "SCORING_FAIRNESS"
    COPYRIGHT = "COPYRIGHT"
    PAYMENT = "PAYMENT"


class DisputeSubjectRefKind(str, Enum):
    SUBMISSION = "SUBMISSION"
    REVIEW_ASSIGNMENT = "REVIEW_ASSIGNMENT"
    COPYRIGHT_TRANSFER = "COPYRIGHT_TRANSFER"
    PRIZE_PAYMENT = "PRIZE_PAYMENT"


class DisputeFilerKind(str, Enum):
    CLIENT = "CLIENT"
    DESIGNER = "DESIGNER"
    REVIEWER = "REVIEWER"
    PLATFORM = "PLATFORM"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    MEDIATING_STAGE1 = "MEDIATING_STAGE1"
    MEDIATING_STAGE2 = "MEDIATING_STAGE2"
    ARBITRATION = "ARBITRATION"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"
    WITHDRAWN = "WITHDRAWN"


class CopyrightScope(str, Enum):
    FULL = "FULL"
    LIMITED = "LIMITED"


class CopyrightTransferStatus(str, Enum):
    DRAFTED = "DRAFTED"
    PENDING_SIGNATURES = "PENDING_SIGNATURES"
    ALL_SIGNED = "ALL_SIGNED"
    REGISTERING = "REGISTERING"
    REGISTERED = "REGISTERED"
    VOIDED = "VOIDED"


class SignerPartyKind(str, Enum):
    CLIENT = "CLIENT"
    DESIGNER = "DESIGNER"
    PLATFORM_NOTARY = "PLATFORM_NOTARY"


class PrizeTierKind(str, Enum):
    MAIN = "MAIN"
    CONSOLATION = "CONSOLATION"


class PrizePaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAYING = "PAYING"
    PAID = "PAID"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class AuditActionKind(str, Enum):
    REVIEW_SUBMITTED = "REVIEW_SUBMITTED"
    REVIEW_VOIDED = "REVIEW_VOIDED"
    REVIEW_DISPUTED = "REVIEW_DISPUTED"
    STAGE_PUBLISHED = "STAGE_PUBLISHED"
    COPYRIGHT_DRAFTED = "COPYRIGHT_DRAFTED"
    COPYRIGHT_SIGNED = "COPYRIGHT_SIGNED"
    COPYRIGHT_REGISTERED = "COPYRIGHT_REGISTERED"
    COPYRIGHT_VOIDED = "COPYRIGHT_VOIDED"
    DISPUTE_FILED = "DISPUTE_FILED"
    DISPUTE_RESOLVED = "DISPUTE_RESOLVED"
    PRIZE_PAID = "PRIZE_PAID"


class AuditActorKind(str, Enum):
    CLIENT = "CLIENT"
    DESIGNER = "DESIGNER"
    REVIEWER = "REVIEWER"
    PLATFORM = "PLATFORM"
    SYSTEM = "SYSTEM"


class AuditSubjectKind(str, Enum):
    SUBMISSION = "SUBMISSION"
    REVIEW_ASSIGNMENT = "REVIEW_ASSIGNMENT"
    REVIEW_STAGE = "REVIEW_STAGE"
    COPYRIGHT_TRANSFER = "COPYRIGHT_TRANSFER"
    DISPUTE = "DISPUTE"
    PRIZE_PAYMENT = "PRIZE_PAYMENT"


class InboundEventType(str, Enum):
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    COPYRIGHT_REGISTERED = "COPYRIGHT_REGISTERED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 + entity field tables)
# ---------------------------------------------------------------------------
# Entities carrying id + created_at + updated_at + version (common_fields).
class Client(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    status: str
    tax_jurisdiction: str
    created_at: str
    updated_at: str
    version: int


class Designer(TypedDict, total=False):
    id: str
    display_name: str
    qualification_level: str
    categories: List[str]
    tax_residency: str
    status: str
    trust_score: float
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    client_id: str
    category_code: str
    title: str
    brief: str
    reference_material_urls: List[str]
    prize_pool_cents: int
    opens_at: str
    submission_deadline: str
    final_decision_deadline: str
    status: str
    max_submissions_per_designer: int
    client_participates_final: bool
    anonymity_unmasked_at: Optional[str]
    published_winner_list: List[str]
    created_at: str
    updated_at: str
    version: int


class ReviewStage(TypedDict, total=False):
    id: str
    project_id: str
    stage_kind: str
    passing_threshold: float
    reviewer_quorum: int
    rubric: Dict[str, float]
    starts_at: str
    ends_at: str
    status: str
    advancing_submission_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict, total=False):
    id: str
    project_id: str
    designer_id: Optional[str]
    title: str
    asset_urls: List[str]
    original_work_declared: bool
    status: str
    modify_window_closes_at: Optional[str]
    originality_score: float
    originality_variant: str
    aggregate_score_by_stage: Dict[str, float]
    prize_tier_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewAssignment(TypedDict, total=False):
    id: str
    review_stage_id: str
    submission_id: str
    reviewer_id: str
    anonymized_alias: str
    criterion_scores: Dict[str, float]
    aggregated_score: float
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    project_id: str
    dispute_type: str
    subject_ref_kind: str
    subject_ref_id: str
    filer_kind: str
    filer_id: str
    evidence_urls: List[str]
    status: str
    resolution_note: Optional[str]
    filed_within_window: bool
    created_at: str
    updated_at: str
    version: int


class CopyrightTransfer(TypedDict, total=False):
    id: str
    project_id: str
    submission_id: str
    scope: str
    usage_rights: List[str]
    signers: List[Dict[str, Any]]
    status: str
    registration_ref: Optional[str]
    registered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrizeTier(TypedDict, total=False):
    id: str
    project_id: str
    rank: int
    gross_amount_cents: int
    tier_kind: str
    winner_submission_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrizePayment(TypedDict, total=False):
    id: str
    project_id: str
    prize_tier_id: str
    designer_id: str
    gross_amount_cents: int
    withholding_cents: int
    net_amount_cents: int
    status: str
    external_payment_ref: Optional[str]
    idempotency_key: str
    created_at: str
    updated_at: str
    version: int


# Reference catalog entities — PRD §2.4 says they carry ONLY id and created_at.
class DesignCategory(TypedDict, total=False):
    id: str
    code: str
    name: str
    similarity_corpus_id: str
    created_at: str


class ReviewerPool(TypedDict, total=False):
    id: str
    reviewer_id: str
    name: str
    categories: List[str]
    max_concurrent_assignments: int
    conflict_designer_ids: List[str]
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    occurred_at: str
    action_kind: str
    actor_kind: str
    actor_id: str
    subject_kind: str
    subject_id: str
    payload: Dict[str, Any]
    created_at: str


__all__ = [
    "UserRole",
    "ClientStatus", "ClientTaxJurisdiction",
    "DesignerQualificationLevel", "DesignerTaxResidency", "DesignerStatus",
    "ProjectStatus",
    "ReviewStageKind", "ReviewStageStatus",
    "SubmissionStatus", "OriginalityVariant",
    "ReviewAssignmentStatus",
    "DisputeType", "DisputeSubjectRefKind", "DisputeFilerKind", "DisputeStatus",
    "CopyrightScope", "CopyrightTransferStatus", "SignerPartyKind",
    "PrizeTierKind", "PrizePaymentStatus",
    "AuditActionKind", "AuditActorKind", "AuditSubjectKind",
    "InboundEventType",
    "Client", "Designer", "Project", "ReviewStage", "Submission",
    "ReviewAssignment", "Dispute", "CopyrightTransfer", "PrizeTier",
    "PrizePayment", "DesignCategory", "ReviewerPool", "AuditEvent",
]
