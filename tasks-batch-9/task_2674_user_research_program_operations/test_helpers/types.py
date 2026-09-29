"""Enumerations and resource shapes for the User Research Program Operations API."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1)
# ---------------------------------------------------------------------------
class Role(str, Enum):
    STAKEHOLDER = "Stakeholder"
    RESEARCHER = "Researcher"
    RESEARCH_LEAD = "ResearchLead"
    PRIVACY_OFFICER = "PrivacyOfficer"
    RESEARCH_OPS_ADMIN = "ResearchOpsAdmin"


ALL_ROLES = [r.value for r in Role]


# ---------------------------------------------------------------------------
# Roadmap decision (PRD 3.1)
# ---------------------------------------------------------------------------
class DecisionStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class Reversibility(str, Enum):
    IRREVERSIBLE = "IRREVERSIBLE"
    REVERSIBLE = "REVERSIBLE"


# ---------------------------------------------------------------------------
# Research request (PRD 3.1)
# ---------------------------------------------------------------------------
class RequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    NEEDS_REFRAMING = "NEEDS_REFRAMING"
    REJECTED = "REJECTED"
    IN_STUDY = "IN_STUDY"
    CLOSED = "CLOSED"


class QuestionType(str, Enum):
    DISCOVERY = "DISCOVERY"
    EVALUATIVE = "EVALUATIVE"
    BEHAVIORAL_LONGITUDINAL = "BEHAVIORAL_LONGITUDINAL"
    MEASUREMENT = "MEASUREMENT"


class EvidenceGap(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class TriageOutcome(str, Enum):
    APPROVED = "APPROVED"
    NEEDS_REFRAMING = "NEEDS_REFRAMING"
    REJECTED = "REJECTED"


class ResearchMethod(str, Enum):
    INTERVIEW = "INTERVIEW"
    USABILITY_TEST = "USABILITY_TEST"
    DIARY_STUDY = "DIARY_STUDY"
    SURVEY = "SURVEY"


# ---------------------------------------------------------------------------
# Participant pool and participants (PRD 3.2)
# ---------------------------------------------------------------------------
class PoolStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class PoolType(str, Enum):
    CUSTOMER_LIST = "CUSTOMER_LIST"
    EXTERNAL_PANEL = "EXTERNAL_PANEL"
    INTERNAL_DOGFOOD = "INTERNAL_DOGFOOD"


class ParticipantStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    COOLDOWN = "COOLDOWN"
    SUPPRESSED = "SUPPRESSED"


# ---------------------------------------------------------------------------
# Study (PRD 3.3)
# ---------------------------------------------------------------------------
class ExecutionStatus(str, Enum):
    PLANNED = "PLANNED"
    GUIDE_APPROVED = "GUIDE_APPROVED"
    FIELDING = "FIELDING"
    ANALYSIS = "ANALYSIS"
    REPORTED = "REPORTED"
    CLOSED = "CLOSED"


class RecruitmentStatusDimension(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    RECRUITING = "RECRUITING"
    QUOTA_MET = "QUOTA_MET"
    RECRUITMENT_FAILED = "RECRUITMENT_FAILED"


class GuideStatus(str, Enum):
    NONE = "NONE"
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"


# ---------------------------------------------------------------------------
# Recruitment (PRD 3.4, 3.5)
# ---------------------------------------------------------------------------
class RecruitmentStatus(str, Enum):
    INVITED = "INVITED"
    SCREENED_IN = "SCREENED_IN"
    SCREENED_OUT = "SCREENED_OUT"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    WITHDRAWN = "WITHDRAWN"


class IncentiveState(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"
    PAID = "PAID"


# ---------------------------------------------------------------------------
# Consent and artifacts (PRD 3.6)
# ---------------------------------------------------------------------------
class ConsentStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ConsentScope(str, Enum):
    RECORDING = "RECORDING"
    TRANSCRIPT = "TRANSCRIPT"
    PII_QUOTE = "PII_QUOTE"


class ArtifactType(str, Enum):
    RECORDING = "RECORDING"
    TRANSCRIPT = "TRANSCRIPT"
    PII_NOTE = "PII_NOTE"


class ArtifactLifecycleState(str, Enum):
    RETAINED = "RETAINED"
    PURGED = "PURGED"


# ---------------------------------------------------------------------------
# Repository: themes, findings, evidence links (PRD 3.7)
# ---------------------------------------------------------------------------
class ThemeStatus(str, Enum):
    EMERGING = "EMERGING"
    ESTABLISHED = "ESTABLISHED"


class FindingStatus(str, Enum):
    DRAFT = "DRAFT"
    EVIDENCE_LOCKED = "EVIDENCE_LOCKED"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


class StrengthVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CORROBORATED = "CORROBORATED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class WeightClass(str, Enum):
    DIRECT_QUOTE = "DIRECT_QUOTE"
    OBSERVED_BEHAVIOR = "OBSERVED_BEHAVIOR"
    SELF_REPORT = "SELF_REPORT"


# ---------------------------------------------------------------------------
# Readouts and follow-ups (PRD 3.8)
# ---------------------------------------------------------------------------
class ReadoutStatus(str, Enum):
    DRAFT = "DRAFT"
    SUPERSEDED = "SUPERSEDED"
    DELIVERED = "DELIVERED"
    ACCEPTED = "ACCEPTED"
    DEFERRED = "DEFERRED"


class RecommendedAction(str, Enum):
    PROCEED = "PROCEED"
    PIVOT = "PIVOT"
    HOLD = "HOLD"


class ResponseOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    DEFERRED = "DEFERRED"


class FollowUpStatus(str, Enum):
    OPEN = "OPEN"
    OVERDUE = "OVERDUE"
    DONE = "DONE"


# ---------------------------------------------------------------------------
# Settlement (PRD 3.9)
# ---------------------------------------------------------------------------
class SettlementMode(str, Enum):
    FORWARD_ESTIMATE = "FORWARD_ESTIMATE"
    CHRONOLOGICAL_ACTUAL = "CHRONOLOGICAL_ACTUAL"


# ---------------------------------------------------------------------------
# Resource shapes.  Every one of the thirteen resource types carries
# ``created_at``, ``updated_at`` and ``version`` (PRD 2.4).
# ---------------------------------------------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class RoadmapDecisionShape(CommonFields):
    title: str
    decision_deadline: str
    reversibility: str
    impacted_user_count: int
    status: str
    evidence_confidence: float
    locked_at: Optional[str]


class ResearchRequestShape(CommonFields):
    roadmap_decision_id: str
    requester_user_id: str
    question: str
    question_type: str
    evidence_gap: str
    status: str
    priority_score: Optional[float]
    recommended_method: Optional[str]
    approved_method: Optional[str]
    revision_round: int
    triage_reason: Optional[str]
    triaged_at: Optional[str]


class ParticipantPoolShape(CommonFields):
    name: str
    pool_type: str
    contact_cap_per_window: int
    contact_window_days: int
    incentive_budget_cents: int
    incentive_reserved_cents: int
    incentive_paid_cents: int
    incentive_available_cents: int
    last_estimate_cents: Optional[int]
    settled_study_ids: List[str]
    status: str
    participant_count: int
    suppressed_participant_count: int


class ParticipantShape(CommonFields):
    pool_id: str
    external_ref: str
    segment: str
    locale: str
    pii_on_file: bool
    last_contacted_at: Optional[str]
    contacts_in_window: int
    no_show_strikes: int
    status: str


class StudyShape(CommonFields):
    research_request_id: str
    participant_pool_id: str
    lead_user_id: str
    method: str
    target_participant_count: int
    screening_criteria: Dict[str, Any]
    incentive_amount_cents: int
    fielding_start: str
    fielding_end: str
    guide_version_label: Optional[str]
    guide_question_count: Optional[int]
    guide_status: str
    guide_version_pinned: Optional[str]
    execution_status: str
    recruitment_status: str
    invited_count: int
    screened_in_count: int
    completed_count: int
    fielded_at: Optional[str]
    fielding_closed_at: Optional[str]


class RecruitmentShape(CommonFields):
    study_id: str
    participant_id: str
    screening_answers: Optional[Dict[str, Any]]
    screen_score: Optional[float]
    status: str
    incentive_state: str
    reserved_cents: int
    paid_cents: int
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    moderator_user_id: Optional[str]
    guide_version_pinned: Optional[str]
    actual_duration_min: Optional[int]
    reschedule_count: int
    closure_reason: Optional[str]


class ConsentRecordShape(CommonFields):
    participant_id: str
    study_id: str
    scopes: List[str]
    retention_days: int
    granted_at: str
    retention_until: str
    status: str
    revoked_at: Optional[str]
    revocation_reason: Optional[str]


class ResearchArtifactShape(CommonFields):
    recruitment_id: str
    artifact_type: str
    contains_pii: bool
    retention_until: str
    lifecycle_state: str
    purged_at: Optional[str]
    purge_reason: Optional[str]


class ThemeShape(CommonFields):
    label: str
    parent_theme_id: Optional[str]
    depth: int
    own_evidence_weight: float
    evidence_weight: float
    reuse_count: int
    status: str


class FindingShape(CommonFields):
    study_id: str
    theme_id: str
    authored_by_user_id: str
    statement: str
    severity: str
    evidence_strength: float
    strength_variant: str
    admissible_link_count: int
    distinct_participant_count: int
    status: str
    retraction_reason: Optional[str]
    published_at: Optional[str]


class EvidenceLinkShape(CommonFields):
    finding_id: str
    artifact_id: str
    excerpt_ref: str
    weight_class: str
    contribution: float
    is_admissible: bool
    inadmissible_reason: Optional[str]


class ReadoutShape(CommonFields):
    study_id: str
    roadmap_decision_id: str
    recommendation: str
    recommended_action: str
    cited_finding_ids: List[str]
    status: str
    delivered_at: Optional[str]
    responded_at: Optional[str]
    response_note: Optional[str]
    decision_confidence_before: Optional[float]
    decision_confidence_after: Optional[float]


class FollowUpShape(CommonFields):
    readout_id: str
    owner_user_id: str
    description: str
    due_date: str
    status: str
    completed_at: Optional[str]


class StudyMetricsShape(TypedDict):
    cycle_time_days: Optional[int]
    fielding_days: Optional[int]
    recruitment_efficiency: float
    published_findings: int
    impact_score: float


class RetentionSweepShape(TypedDict):
    expired_consent_count: int
    purged_artifact_count: int
    inadmissible_link_count: int
    retracted_finding_count: int
    overdue_follow_up_count: int
    unlocked_decision_count: int
