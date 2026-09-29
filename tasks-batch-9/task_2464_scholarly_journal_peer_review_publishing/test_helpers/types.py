"""Domain types for the Scholarly Journal Peer Review & Publishing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    EDITOR_IN_CHIEF = "EditorInChief"
    HANDLING_EDITOR = "HandlingEditor"
    REVIEWER = "Reviewer"
    AUTHOR = "Author"
    PRODUCTION_STAFF = "ProductionStaff"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class ConsensusMode(str, Enum):
    UNWEIGHTED = "UNWEIGHTED"
    RELIABILITY_WEIGHTED = "RELIABILITY_WEIGHTED"


class EditorRoleLevel(str, Enum):
    HANDLING = "HANDLING"
    CHIEF = "CHIEF"


class EditorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"


class CountryIncomeBand(str, Enum):
    HIGH = "HIGH"
    UPPER_MIDDLE = "UPPER_MIDDLE"
    LOWER_MIDDLE = "LOWER_MIDDLE"
    LOW = "LOW"


class ReviewerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    RETIRED = "RETIRED"


class OaLicense(str, Enum):
    CC_BY = "CC_BY"
    CC_BY_NC = "CC_BY_NC"
    CC_BY_NC_ND = "CC_BY_NC_ND"
    GREEN_SELF_ARCHIVE = "GREEN_SELF_ARCHIVE"


class ManuscriptStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DECISION_PENDING = "DECISION_PENDING"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    REVISION_SUBMITTED = "REVISION_SUBMITTED"
    REJECTED = "REJECTED"
    UNDER_APPEAL = "UNDER_APPEAL"
    IN_PRODUCTION = "IN_PRODUCTION"
    PUBLISHED = "PUBLISHED"
    CORRECTED = "CORRECTED"
    DESK_REJECTED = "DESK_REJECTED"
    RETRACTED = "RETRACTED"


class IntegrityStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FLAG = "FLAG"
    BLOCK = "BLOCK"


class FormattingStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class ScanType(str, Enum):
    PLAGIARISM = "PLAGIARISM"
    IMAGE_FORENSICS = "IMAGE_FORENSICS"


class ScreeningVerdict(str, Enum):
    PASS = "PASS"
    FLAG = "FLAG"
    BLOCK = "BLOCK"


class SelectedBy(str, Enum):
    EXPLICIT = "EXPLICIT"
    SELECTOR = "SELECTOR"


class AssignmentState(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    RECUSED = "RECUSED"
    RELEASED = "RELEASED"


class ConflictType(str, Enum):
    CO_AUTHOR = "CO_AUTHOR"
    SAME_INSTITUTION = "SAME_INSTITUTION"
    FINANCIAL = "FINANCIAL"
    PERSONAL = "PERSONAL"


class ReleasedReason(str, Enum):
    DECISION_FINAL = "DECISION_FINAL"
    RECUSAL = "RECUSAL"
    RETRACTION = "RETRACTION"


class InvitationState(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"


class ClosedReason(str, Enum):
    REVIEW_SUBMITTED = "REVIEW_SUBMITTED"
    REVIEWER_DECLINED = "REVIEWER_DECLINED"
    SWEEP_EXPIRY = "SWEEP_EXPIRY"
    EDITOR_WITHDRAWN = "EDITOR_WITHDRAWN"
    DECISION_CASCADE = "DECISION_CASCADE"


class Recommendation(str, Enum):
    ACCEPT = "ACCEPT"
    MINOR_REVISION = "MINOR_REVISION"
    MAJOR_REVISION = "MAJOR_REVISION"
    REJECT = "REJECT"


class DecisionCategory(str, Enum):
    ACCEPT = "ACCEPT"
    MINOR_REVISION = "MINOR_REVISION"
    MAJOR_REVISION = "MAJOR_REVISION"
    REJECT = "REJECT"
    REJECT_AND_RESUBMIT = "REJECT_AND_RESUBMIT"


class CategorySource(str, Enum):
    EXPLICIT = "EXPLICIT"
    AUTO = "AUTO"


class AppealState(str, Enum):
    FILED = "FILED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class EthicsCaseType(str, Enum):
    AUTHORSHIP_DISPUTE = "AUTHORSHIP_DISPUTE"
    DATA_AVAILABILITY = "DATA_AVAILABILITY"
    IMAGE_INTEGRITY = "IMAGE_INTEGRITY"
    PLAGIARISM = "PLAGIARISM"


class EthicsCaseSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class EthicsCaseOpenedBy(str, Enum):
    MANUAL = "MANUAL"
    SCREENING_CASCADE = "SCREENING_CASCADE"


class EthicsCaseState(str, Enum):
    OPEN = "OPEN"
    INVESTIGATION = "INVESTIGATION"
    AUTHOR_RESPONSE_REQUESTED = "AUTHOR_RESPONSE_REQUESTED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    RESOLVED_NO_ACTION = "RESOLVED_NO_ACTION"
    CORRECTION_ISSUED = "CORRECTION_ISSUED"
    RETRACTION_APPROVED = "RETRACTION_APPROVED"


class ContentStage(str, Enum):
    COPYEDITING = "COPYEDITING"
    TYPESETTING = "TYPESETTING"
    PROOF_SENT = "PROOF_SENT"
    PROOF_APPROVED = "PROOF_APPROVED"
    TERMINATED = "TERMINATED"


class ClearanceStage(str, Enum):
    LICENSE_PENDING = "LICENSE_PENDING"
    FEE_CLEARED = "FEE_CLEARED"
    DEPOSIT_CONFIRMED = "DEPOSIT_CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class ArchivalRepository(str, Enum):
    CLOCKSS = "CLOCKSS"
    PORTICO = "PORTICO"
    LOCKSS = "LOCKSS"


class IndexingStatus(str, Enum):
    NOT_INDEXED = "NOT_INDEXED"
    INDEXED = "INDEXED"
    WITHDRAWN = "WITHDRAWN"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Entity shapes.
#
# Journal, Editor, Author, Reviewer, Manuscript, EditorAssignment,
# ReviewInvitation, Appeal, EthicsCase, ProductionJob and APCInvoice carry
# id + created_at + updated_at + version (PRD §2.4).
#
# IntegrityScreening, Review and Decision are append-only evidence and carry
# only id + created_at — no updated_at and no version (PRD §2.4).
# --------------------------------------------------------------------------


class Journal(TypedDict):
    id: str
    name: str
    subject_areas: List[str]
    doi_prefix: str
    min_completed_reviews_for_decision: int
    max_revision_rounds: int
    review_target_days: int
    reminder_cadence_days: int
    max_reminders_per_invitation: int
    reviewer_concurrent_window_limit: int
    consensus_mode: str
    max_page_count: int
    max_figure_count: int
    requires_data_availability_statement: bool
    apc_base_cents: int
    page_charge_cents_per_page: int
    color_figure_charge_cents: int
    embargo_months: int
    typeset_changeover_buffer_days: int
    max_proof_rounds: int
    manuscript_intake_count: int
    published_article_count: int
    retracted_article_count: int
    apc_receivable_cents: int
    apc_waived_cents: int
    created_at: str
    updated_at: str
    version: int


class Editor(TypedDict):
    id: str
    journal_id: str
    email: str
    full_name: str
    affiliation: str
    subject_areas: List[str]
    role_level: str
    status: str
    max_concurrent_assignments: int
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Author(TypedDict):
    id: str
    email: str
    full_name: str
    affiliation: str
    country_income_band: str
    institutional_agreement: bool
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict):
    id: str
    email: str
    full_name: str
    affiliation: str
    subject_areas: List[str]
    status: str
    invited_count: int
    accepted_count: int
    declined_count: int
    expired_count: int
    submitted_count: int
    late_days_total: int
    open_invitation_count: int
    reliability_score_rolling: float
    reliability_score_lifetime: float
    created_at: str
    updated_at: str
    version: int


class Manuscript(TypedDict):
    id: str
    journal_id: str
    corresponding_author_id: str
    supersedes_manuscript_id: Optional[str]
    title: str
    subject_area: str
    oa_license: str
    page_count: int
    figure_count: int
    coauthor_emails: List[str]
    data_availability_statement: Optional[str]
    status: str
    revision_round: int
    journal_sequence_number: int
    integrity_status: str
    formatting_status: str
    submitted_review_count: int
    review_shortfall_flag: bool
    handling_gap_flag: bool
    consensus_index_at_last_decision: Optional[float]
    decision_count: int
    publication_date: Optional[str]
    embargo_end_date: Optional[str]
    doi: Optional[str]
    retracted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntegrityScreening(TypedDict):
    # Append-only evidence: no updated_at, no version.
    id: str
    manuscript_id: str
    round: int
    scan_type: str
    similarity_pct: Optional[float]
    manipulated_figure_count: Optional[int]
    verdict: str
    created_at: str


class EditorAssignment(TypedDict):
    id: str
    manuscript_id: str
    editor_id: str
    selected_by: str
    state: str
    declared_conflict: Optional[bool]
    conflict_type: Optional[str]
    replaced_assignment_id: Optional[str]
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewInvitation(TypedDict):
    id: str
    manuscript_id: str
    reviewer_id: str
    round: int
    state: str
    selected_by: str
    invited_at: str
    due_at: str
    responded_at: Optional[str]
    decline_reason: Optional[str]
    reminder_count: int
    last_reminder_at: Optional[str]
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    # Append-only evidence: no updated_at, no version.
    id: str
    invitation_id: str
    recommendation: str
    novelty_score: int
    rigor_score: int
    clarity_score: int
    comments: Optional[str]
    submitted_at: str
    days_late: int
    reliability_weight: float
    created_at: str


class Decision(TypedDict):
    # Append-only evidence: no updated_at, no version.
    id: str
    manuscript_id: str
    decided_by_editor_id: str
    round: int
    category: str
    category_source: str
    consensus_mode: str
    consensus_index: float
    auto_category: str
    reviews_counted: int
    editorial_note: str
    created_at: str


class Appeal(TypedDict):
    id: str
    decision_id: str
    manuscript_id: str
    adjudicated_by_editor_id: Optional[str]
    state: str
    grounds: str
    rationale: Optional[str]
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EthicsCase(TypedDict):
    id: str
    manuscript_id: str
    case_type: str
    severity: str
    opened_by: str
    state: str
    description: str
    resolution_statement: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionJob(TypedDict):
    id: str
    manuscript_id: str
    content_stage: str
    clearance_stage: str
    proof_round: int
    slot_start: Optional[str]
    slot_end: Optional[str]
    archival_repository: Optional[str]
    deposit_reference: Optional[str]
    indexing_status: str
    issue_label: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class APCInvoice(TypedDict):
    id: str
    manuscript_id: str
    license_at_issue: str
    base_cents: int
    waiver_pct: int
    waiver_cents: int
    institutional_pct: int
    institutional_cents: int
    net_apc_cents: int
    auto_waived: bool
    page_charge_count: int
    color_figure_count: int
    raw_surcharge_cents: int
    provisional_total_cents: int
    surcharge_relief_pct: int
    surcharge_cents: int
    total_due_cents: int
    status: str
    waiver_reason: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
