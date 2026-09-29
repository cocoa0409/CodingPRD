"""Domain types for the Crisis Communications Program API.

Entity state enumerations, vocabulary enumerations and role names, all spelled
exactly as the PRD spells them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    INCIDENT_LEAD = "IncidentLead"
    LEGAL_COUNSEL = "LegalCounsel"
    COMMS_LEAD = "CommsLead"
    SPOKESPERSON = "Spokesperson"
    SOCIAL_LISTENER = "SocialListener"
    EXEC_SPONSOR = "ExecSponsor"


ALL_ROLES: List[str] = [r.value for r in UserRole]

# The six roles whose X-User-ID is the id of the acting TeamMember.
ENTITY_BACKED_ROLES: List[str] = [
    UserRole.INCIDENT_LEAD.value,
    UserRole.LEGAL_COUNSEL.value,
    UserRole.COMMS_LEAD.value,
    UserRole.SPOKESPERSON.value,
    UserRole.SOCIAL_LISTENER.value,
    UserRole.EXEC_SPONSOR.value,
]

# ProgramAdmin's X-User-ID is an opaque operator identifier.
OPAQUE_ROLES: List[str] = [UserRole.PROGRAM_ADMIN.value]


# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------


class ScenarioCode(str, Enum):
    PRODUCT_RECALL = "PRODUCT_RECALL"
    DATA_BREACH = "DATA_BREACH"
    EXEC_MISCONDUCT = "EXEC_MISCONDUCT"
    PLANT_INCIDENT = "PLANT_INCIDENT"
    REGULATORY_PROBE = "REGULATORY_PROBE"


class ChannelType(str, Enum):
    MEDIA = "MEDIA"
    SOCIAL = "SOCIAL"
    REGULATORY = "REGULATORY"


class EscalationPathState(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class MediaTrainingStatus(str, Enum):
    NONE = "NONE"
    CURRENT = "CURRENT"


class SourceCredibilityTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class MaterialType(str, Enum):
    DARK_SITE_PAGE = "DARK_SITE_PAGE"
    FAQ = "FAQ"
    HOLDING_TEMPLATE = "HOLDING_TEMPLATE"
    EXEC_BRIEF = "EXEC_BRIEF"


class ReadinessState(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    STALE = "STALE"


class TeamRole(str, Enum):
    INCIDENT_LEAD = "INCIDENT_LEAD"
    LEGAL_COUNSEL = "LEGAL_COUNSEL"
    COMMS_LEAD = "COMMS_LEAD"
    SPOKESPERSON = "SPOKESPERSON"
    SOCIAL_LISTENER = "SOCIAL_LISTENER"
    EXEC_SPONSOR = "EXEC_SPONSOR"


class DecisionAuthority(str, Enum):
    FULL = "FULL"
    LIMITED = "LIMITED"


class StatementType(str, Enum):
    HOLDING = "HOLDING"
    UPDATE = "UPDATE"
    CORRECTION = "CORRECTION"
    FINAL = "FINAL"


class Audience(str, Enum):
    EMPLOYEE = "EMPLOYEE"
    CUSTOMER = "CUSTOMER"
    REGULATOR = "REGULATOR"
    INVESTOR = "INVESTOR"
    MEDIA = "MEDIA"


class SeverityTier(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class SeverityBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ScoringMethod(str, Enum):
    RAW = "RAW"
    ADJUSTED = "ADJUSTED"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AmplificationBand(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class ResolutionBranch(str, Enum):
    PLATFORM = "PLATFORM"
    CORRECTION = "CORRECTION"


# ---------------------------------------------------------------------------
# State machines
# ---------------------------------------------------------------------------


class IssueSignalState(str, Enum):
    OPEN = "OPEN"
    LINKED = "LINKED"
    ESCALATED = "ESCALATED"


class IncidentResponseState(str, Enum):
    MONITORING = "MONITORING"
    ACTIVATED = "ACTIVATED"
    RESOLVED = "RESOLVED"


class IncidentPrivilegeState(str, Enum):
    NON_PRIVILEGED = "NON_PRIVILEGED"
    PRIVILEGED_ASSERTED = "PRIVILEGED_ASSERTED"
    PRIVILEGE_WAIVED = "PRIVILEGE_WAIVED"


class CommsPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class TeamAssignmentState(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    STOOD_DOWN = "STOOD_DOWN"


class StatementState(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ApprovalTaskState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class StakeholderNoticeState(str, Enum):
    QUEUED = "QUEUED"
    BLOCKED = "BLOCKED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class MediaInterviewState(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class MisinformationClaimState(str, Enum):
    DETECTED = "DETECTED"
    TRIAGED = "TRIAGED"
    PLATFORM_ESCALATED = "PLATFORM_ESCALATED"
    CORRECTION_ISSUED = "CORRECTION_ISSUED"
    CLOSED = "CLOSED"


class PostCrisisReviewState(str, Enum):
    OPEN = "OPEN"
    SCORED = "SCORED"


# ---------------------------------------------------------------------------
# Entity shapes. All twelve resources carry id / created_at / updated_at /
# version (PRD §2.4).
# ---------------------------------------------------------------------------


class TeamMember(TypedDict):
    id: str
    full_name: str
    org_title: str
    privilege_cleared: bool
    media_training_status: str
    media_training_expires_at: Optional[str]
    scheduled_interview_minutes: int
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class MonitoredChannel(TypedDict):
    id: str
    name: str
    channel_type: str
    platform_escalation_contact: Optional[str]
    max_concurrent_corrections: int
    escalation_path_state: str
    verified_contact_reference: Optional[str]
    reserved_correction_minutes: int
    open_escalation_count: int
    created_at: str
    updated_at: str
    version: int


class IssueSignal(TypedDict):
    id: str
    channel_id: str
    incident_id: Optional[str]
    headline: str
    reach_score: int
    sentiment_score: float
    source_credibility_tier: str
    regulatory_flag: bool
    escalation_score: float
    state: str
    detected_at: str
    escalated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    title: str
    scenario_code: str
    created_by_member_id: str
    response_state: str
    privilege_state: str
    comms_posture: str
    legal_hold_active: bool
    privilege_basis: Optional[str]
    sla_breached: bool
    severity_tier: Optional[str]
    severity_basis: Optional[str]
    severity_score: Optional[float]
    final_severity_tier: Optional[str]
    final_severity_score: Optional[float]
    activated_at: Optional[str]
    resolved_at: Optional[str]
    holding_statement_due_at: Optional[str]
    holding_statement_published_at: Optional[str]
    base_containment_score: Optional[float]
    amplification_rate_applied: Optional[float]
    containment_priority_score: Optional[float]
    linked_signal_count: int
    escalated_signal_count: int
    open_approval_task_count: int
    blocked_notice_count: int
    released_notice_count: int
    open_claim_count: int
    confirmed_interview_count: int
    stakeholder_reach_index: float
    reputation_index_before: float
    reputation_index_after: Optional[float]
    reputation_delta_reported: Optional[float]
    created_at: str
    updated_at: str
    version: int


class TeamAssignment(TypedDict):
    id: str
    incident_id: str
    member_id: str
    team_role: str
    decision_authority: str
    state: str
    acknowledged_at: Optional[str]
    stood_down_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Statement(TypedDict):
    id: str
    incident_id: str
    statement_type: str
    body: str
    privilege_marked: bool
    supersedes_statement_id: Optional[str]
    drafted_by_member_id: str
    state: str
    revision_round: int
    revision_locked: bool
    quorum_required: int
    approvals_recorded: int
    submitted_at: Optional[str]
    review_deadline_at: Optional[str]
    approved_at: Optional[str]
    published_at: Optional[str]
    approval_latency_minutes: Optional[int]
    withdraw_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ApprovalTask(TypedDict):
    id: str
    statement_id: str
    assignee_member_id: str
    required_team_role: str
    revision_round: int
    is_veto_seat: bool
    state: str
    decision_comment: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StakeholderNotice(TypedDict):
    id: str
    incident_id: str
    statement_id: str
    audience: str
    estimated_reach: int
    embargo_until: Optional[str]
    sequence_rank: int
    state: str
    reach_contribution: float
    released_at: Optional[str]
    priority_override_used: bool
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreparedMaterial(TypedDict):
    id: str
    scenario_code: str
    material_type: str
    title: str
    dark_site_url: Optional[str]
    readiness_state: str
    readiness_score: float
    last_reviewed_at: Optional[str]
    reviewer_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MediaInterview(TypedDict):
    id: str
    incident_id: str
    spokesperson_member_id: str
    channel_id: str
    outlet_name: str
    scheduled_start_at: str
    scheduled_end_at: str
    duration_minutes: int
    anticipated_question_count: int
    high_risk_answers_approved_count: int
    state: str
    confirmed_at: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MisinformationClaim(TypedDict):
    id: str
    incident_id: str
    channel_id: str
    claim_text: str
    virality_score: float
    state: str
    correction_statement_id: Optional[str]
    correction_window_start: Optional[str]
    correction_window_end: Optional[str]
    correction_window_minutes: int
    resolution_branch: Optional[str]
    takedown_confirmed: bool
    corrected: bool
    outcome_note: Optional[str]
    escalated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PostCrisisReview(TypedDict):
    id: str
    incident_id: str
    state: str
    reputation_index_before: float
    reputation_index_after: float
    exposure_factor: float
    total_claim_count: int
    corrected_claim_count: int
    reputation_delta_raw: Optional[float]
    reputation_delta_adjusted: Optional[float]
    scoring_method: Optional[str]
    reported_delta: Optional[float]
    playbook_update_count: int
    scored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
