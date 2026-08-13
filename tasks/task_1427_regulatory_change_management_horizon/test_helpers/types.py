"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COMPLIANCE_MANAGER = "ComplianceManager"
    BUSINESS_OWNER = "BusinessOwner"
    BOARD_SECRETARY = "BoardSecretary"
    PLATFORM_ADMIN = "PlatformAdmin"


class ChangeStatus(str, Enum):
    PENDING_TRIAGE = "PENDING_TRIAGE"
    TRIAGED_APPLICABLE = "TRIAGED_APPLICABLE"
    TRIAGED_NOT_APPLICABLE = "TRIAGED_NOT_APPLICABLE"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class Applicability(str, Enum):
    UNDETERMINED = "UNDETERMINED"
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class Tier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ObligationStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ControlStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MappingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class AssessmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class GapStatus(str, Enum):
    OPEN = "OPEN"
    IN_REVIEW = "IN_REVIEW"
    CONFIRMED = "CONFIRMED"


class PlanExecutionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_EXECUTION = "IN_EXECUTION"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"


class DeadlinePosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    OVERDUE = "OVERDUE"


class PolicyStatus(str, Enum):
    DRAFTING = "DRAFTING"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


class RolloutStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CLOSED_WITH_EXCEPTIONS = "CLOSED_WITH_EXCEPTIONS"
    CANCELLED = "CANCELLED"


class PackageStatus(str, Enum):
    ASSEMBLING = "ASSEMBLING"
    SEALED = "SEALED"
    SUBMITTED_TO_EXAMINER = "SUBMITTED_TO_EXAMINER"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class EscalationTrigger(str, Enum):
    DEADLINE_BREACH = "DEADLINE_BREACH"
    ZERO_COVERAGE = "ZERO_COVERAGE"


class EscalationTargetType(str, Enum):
    IMPLEMENTATION_PLAN = "IMPLEMENTATION_PLAN"
    OBLIGATION = "OBLIGATION"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PRESENTED = "PRESENTED"


class CommitteeName(str, Enum):
    BOARD_RISK_COMMITTEE = "BOARD_RISK_COMMITTEE"
    AUDIT_COMMITTEE = "AUDIT_COMMITTEE"
    EXECUTIVE_COMPLIANCE_COMMITTEE = "EXECUTIVE_COMPLIANCE_COMMITTEE"


class FeedSource(str, Enum):
    FED_REGISTER = "FED_REGISTER"
    STATE_BULLETIN = "STATE_BULLETIN"
    INT_JOURNAL = "INT_JOURNAL"
    MANUAL_ENTRY = "MANUAL_ENTRY"


# --- Entity TypedDicts (common_fields entities carry id/created_at/updated_at/version) ---


class BusinessOwner(TypedDict, total=False):
    id: str
    name: str
    department: str
    email: str
    active_assessment_count: int
    open_escalation_count: int
    assignment_suspended: bool
    created_at: str
    updated_at: str
    version: int


class RegulatoryChange(TypedDict, total=False):
    id: str
    citation: str
    title: str
    summary: str
    feed_source: str
    jurisdiction: str
    regulator: str
    published_at: str
    effective_date: str
    comment_deadline: Optional[str]
    severity_hint: str
    supersedes_change_id: Optional[str]
    superseded_by_id: Optional[str]
    status: str
    applicability: str
    triage_rationale: Optional[str]
    triage_round: int
    provisional_risk_tier: Optional[str]
    risk_tier: Optional[str]
    business_owner_id: Optional[str]
    created_by_user_id: str
    triaged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Obligation(TypedDict, total=False):
    id: str
    obligation_code: str
    title: str
    regulatory_change_id: str
    criticality: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Control(TypedDict, total=False):
    id: str
    control_code: str
    title: str
    owner_department: str
    review_frequency_days: int
    last_reviewed_at: Optional[str]
    effectiveness_factor: float
    next_review_due: Optional[str]
    policy_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ObligationControlMapping(TypedDict, total=False):
    id: str
    obligation_id: str
    control_id: str
    coverage_weight: int
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ObligationRegister(TypedDict, total=False):
    id: str
    current_version_number: int
    singleton_note: str
    created_at: str
    updated_at: str
    version: int


class ObligationRegisterVersion(TypedDict, total=False):
    # Append-only snapshot: id + created_at only, no updated_at / version.
    id: str
    created_at: str
    version_number: int
    published_at: str
    obligation_codes: List[str]
    obligation_count: int
    register_checksum: str


class ImpactAssessment(TypedDict, total=False):
    id: str
    regulatory_change_id: str
    business_owner_id: str
    due_date: str
    likelihood_score: Optional[int]
    severity_score: Optional[int]
    affected_business_lines: Optional[int]
    findings_summary: Optional[str]
    impact_rating_raw: Optional[float]
    impact_tier: Optional[str]
    sla_breached: bool
    status: str
    supersedes_assessment_id: Optional[str]
    return_count: int
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GapAnalysis(TypedDict, total=False):
    id: str
    impact_assessment_id: str
    obligation_id: str
    requirement_points: int
    covered_points: float
    residual_gap_points: float
    status: str
    confirmed_by_user_id: Optional[str]
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImplementationPlan(TypedDict, total=False):
    id: str
    gap_analysis_id: str
    title: str
    target_completion_date: str
    obligation_id: str
    regulatory_change_id: str
    business_owner_id: str
    execution_status: str
    deadline_posture: str
    pinned_register_version_number: Optional[int]
    extension_count: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    verification_evidence_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PolicyUpdate(TypedDict, total=False):
    id: str
    control_id: str
    implementation_plan_id: Optional[str]
    title: str
    change_summary: str
    effective_date: str
    new_policy_version: Optional[int]
    status: str
    drafted_by_user_id: str
    approved_by_user_id: Optional[str]
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingRollout(TypedDict, total=False):
    id: str
    policy_update_id: str
    control_id: str
    window_start: str
    window_end: str
    attestation_records: List[Dict[str, Any]]
    assigned_count: int
    completed_count: int
    completion_pct: float
    past_due: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class EvidencePackage(TypedDict, total=False):
    id: str
    implementation_plan_id: str
    artifacts: List[Dict[str, Any]]
    artifact_count: int
    status: str
    sealed_at: Optional[str]
    examiner_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Escalation(TypedDict, total=False):
    id: str
    target_type: str
    target_id: str
    trigger_rule: str
    business_owner_id: Optional[str]
    level: int
    status: str
    resolution_code: Optional[str]
    opened_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteeReport(TypedDict, total=False):
    id: str
    committee_name: str
    period_start: str
    period_end: str
    status: str
    metrics: Optional[Dict[str, Any]]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditEvent(TypedDict, total=False):
    # Append-only: id + created_at only, no updated_at / version.
    id: str
    created_at: str
    sequence_number: int
    actor_user_id: str
    actor_role: str
    action: str
    entity_type: str
    entity_id: str
    occurred_at: str
    prev_event_hash: str
    event_hash: str
