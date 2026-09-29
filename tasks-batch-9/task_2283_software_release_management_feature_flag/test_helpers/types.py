"""Entity shapes and enumerations for the Release Management & Feature Flag Governance API.

Mirrors the resource definitions of PRD §2.5 (common fields), §3.1-§3.9 (entity
narratives) and §2.1 (roles).

Two families of resources exist:

* Ten mutable resources carry the full common quartet ``id``, ``created_at``,
  ``updated_at`` and ``version``.
* Five append-only resources -- change dependencies, approvals, change-to-flag
  links, canary evaluations and health samples -- carry only ``id`` and
  ``created_at``; both ``updated_at`` and ``version`` are absent entirely.
"""

from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class Role:
    PLATFORM_ADMIN = "PlatformAdmin"
    RELEASE_MANAGER = "ReleaseManager"
    ENGINEER = "Engineer"
    CHANGE_APPROVER = "ChangeApprover"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SRE = "SRE"

    ALL = [
        PLATFORM_ADMIN,
        RELEASE_MANAGER,
        ENGINEER,
        CHANGE_APPROVER,
        COMPLIANCE_OFFICER,
        SRE,
    ]


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class TrainPhase:
    """Release train ``phase`` (PRD §3.1)."""

    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class TrainFreezeAction:
    FREEZE = "FREEZE"
    UNFREEZE = "UNFREEZE"


class EnvironmentTier:
    """Environment ``tier`` (PRD §3.7)."""

    DEV = "DEV"
    STAGING = "STAGING"
    PROD = "PROD"


class ReleasePhase:
    """Release ``phase`` (PRD §3.2)."""

    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CUT = "CUT"
    STABILIZING = "STABILIZING"
    RELEASED = "RELEASED"
    ROLLED_BACK = "ROLLED_BACK"


class ChangeState:
    """Change request ``state`` (PRD §3.3, §3.4)."""

    DRAFT = "DRAFT"
    RISK_CLASSIFIED = "RISK_CLASSIFIED"
    CAB_REVIEW = "CAB_REVIEW"
    APPROVED = "APPROVED"
    BLOCKED_BY_DEPENDENCY = "BLOCKED_BY_DEPENDENCY"
    MERGED = "MERGED"
    DEPLOYED = "DEPLOYED"
    DEFERRED = "DEFERRED"
    WITHDRAWN = "WITHDRAWN"
    REJECTED = "REJECTED"


class RiskClass:
    """Change request ``risk_class`` (PRD §3.3)."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DeclaredBlastRadius:
    """Change request ``declared_blast_radius`` (PRD §3.3)."""

    INTERNAL = "INTERNAL"
    SINGLE_TENANT = "SINGLE_TENANT"
    GLOBAL = "GLOBAL"


class ApprovalKind:
    """Approval lane (PRD §3.4)."""

    TECHNICAL = "TECHNICAL"
    COMPLIANCE = "COMPLIANCE"
    CAB = "CAB"


class ApprovalDecision:
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class FlagState:
    """Feature flag rollout dimension ``state`` (PRD §3.5)."""

    DRAFT = "DRAFT"
    ACTIVE_ROLLING_OUT = "ACTIVE_ROLLING_OUT"
    PAUSED = "PAUSED"
    FULLY_ROLLED_OUT = "FULLY_ROLLED_OUT"
    ARCHIVED = "ARCHIVED"


class CleanupState:
    """Feature flag hygiene dimension ``cleanup_state`` (PRD §3.5, §3.6)."""

    COMPLIANT = "COMPLIANT"
    WARNING = "WARNING"
    OVERDUE = "OVERDUE"
    ENFORCED = "ENFORCED"


class StepState:
    """Rollout step ``state`` (PRD §3.5)."""

    PLANNED = "PLANNED"
    SOAKING = "SOAKING"
    APPLIED = "APPLIED"
    ABORTED = "ABORTED"
    VOIDED = "VOIDED"


class FlagLinkGuardKind:
    """Change-to-flag link ``guard_kind`` (PRD §3.3)."""

    GATES_ENTIRE_CHANGE = "GATES_ENTIRE_CHANGE"
    PARTIAL = "PARTIAL"


class DeliveryState:
    """Deployment delivery dimension (PRD §3.7)."""

    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CANARY_SOAK = "CANARY_SOAK"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    ROLLED_BACK = "ROLLED_BACK"


class VerificationState:
    """Deployment verification dimension (PRD §3.7)."""

    PENDING = "PENDING"
    PASSING = "PASSING"
    FAILING = "FAILING"
    INCONCLUSIVE = "INCONCLUSIVE"
    WAIVED = "WAIVED"


class DeployStrategy:
    CANARY = "CANARY"
    ALL_AT_ONCE = "ALL_AT_ONCE"
    BLUE_GREEN = "BLUE_GREEN"


class Cohort:
    CANARY = "CANARY"
    BASELINE = "BASELINE"


class CanaryVerdict:
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"


class IncidentSeverity:
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"


class IncidentState:
    OPEN = "OPEN"
    DECIDED = "DECIDED"


class IncidentDecision:
    ROLLBACK = "ROLLBACK"
    FORWARD_FIX = "FORWARD_FIX"
    NO_ACTION = "NO_ACTION"


class NoteAudience:
    CUSTOMER = "CUSTOMER"
    INTERNAL = "INTERNAL"


class NoteState:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class PacketState:
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    SUPERSEDED = "SUPERSEDED"


class EvidenceItem:
    """The six weighted evidence item codes (PRD §3.9)."""

    APPROVALS_COMPLETE = "approvals_complete"
    ROLLBACK_PLANS = "rollback_plans"
    CANARY_PASS = "canary_pass"
    FREEZE_DISCIPLINE = "freeze_discipline"
    FLAG_HYGIENE = "flag_hygiene"
    RELEASE_NOTES = "release_notes"

    ALL = [
        APPROVALS_COMPLETE,
        ROLLBACK_PLANS,
        CANARY_PASS,
        FREEZE_DISCIPLINE,
        FLAG_HYGIENE,
        RELEASE_NOTES,
    ]


class DependencyDirection:
    OUTGOING = "OUTGOING"
    INCOMING = "INCOMING"


# ---------------------------------------------------------------------------
# Mutable resources: full common quartet (PRD §2.5)
# ---------------------------------------------------------------------------


class ReleaseTrain(TypedDict, total=False):
    id: str
    name: str
    cadence_days: int
    code_freeze_lead_hours: int
    stabilization_hours: int
    risk_budget_points: int
    max_concurrent_stabilizing: int
    phase: str
    frozen_at: Optional[str]
    freeze_exception_count: int
    open_release_count: int
    created_at: str
    updated_at: str
    version: int


class Environment(TypedDict, total=False):
    id: str
    name: str
    tier: str
    deploy_window_start_hour_utc: int
    deploy_window_end_hour_utc: int
    cooldown_minutes: int
    blackout_start_at: Optional[str]
    blackout_end_at: Optional[str]
    requires_compliance_evidence: bool
    active_deployment_count: int
    last_deployment_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Release(TypedDict, total=False):
    id: str
    release_train_id: str
    version_label: str
    cut_at: str
    freeze_at: str
    stabilization_end_at: str
    phase: str
    readiness_score_projected: int
    readiness_score_attested: Optional[int]
    rollback_plan_confirmed: bool
    evidence_packet_required: bool
    freeze_exception_approved: bool
    committed_change_count: int
    verified_change_count: int
    risk_budget_consumed_points: int
    released_at: Optional[str]
    rolled_back_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeRequest(TypedDict, total=False):
    id: str
    release_id: str
    title: str
    author_user_id: str
    lines_changed: int
    touched_subsystem_count: int
    has_schema_migration: bool
    declared_blast_radius: str
    rollback_plan: Optional[str]
    rollback_tested: bool
    customer_facing: bool
    summary_customer_facing: Optional[str]
    state: str
    risk_score_preliminary: Optional[int]
    risk_score_final: Optional[int]
    risk_class: Optional[str]
    dependency_depth: int
    approval_technical_count: int
    approval_compliance_count: int
    approval_cab_count: int
    deployment_verified: bool
    merged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FeatureFlag(TypedDict, total=False):
    id: str
    key: str
    owner_user_id: str
    created_by_user_id: str
    expires_at: str
    permanent: bool
    state: str
    cleanup_state: str
    current_exposure_pct: float
    applied_step_count: int
    kill_switch_engaged: bool
    stale_debt_points: int
    last_sweep_at: Optional[str]
    archived_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlagRolloutStep(TypedDict, total=False):
    id: str
    feature_flag_id: str
    deployment_id: Optional[str]
    step_index: int
    target_pct: float
    previous_exposure_pct: Optional[float]
    soak_minutes: int
    state: str
    soak_started_at: Optional[str]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deployment(TypedDict, total=False):
    id: str
    release_id: str
    environment_id: str
    window_start_at: str
    window_end_at: str
    strategy: str
    canary_pct: float
    min_sample_count: int
    abort_error_rate_pct: float
    abort_latency_p95_ms: int
    delivery_state: str
    verification_state: str
    health_score: Optional[float]
    completed_at: Optional[str]
    rolled_back_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    release_train_id: str
    title: str
    severity: str
    detected_at: str
    reporter_user_id: str
    state: str
    decision: Optional[str]
    decided_at: Optional[str]
    linked_release_id: Optional[str]
    linked_deployment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReleaseNoteDocument(TypedDict, total=False):
    id: str
    release_id: str
    audience: str
    state: str
    generated_at: str
    published_at: Optional[str]
    included_change_ids: List[str]
    entry_count: int
    excluded_change_count: int
    created_at: str
    updated_at: str
    version: int


class ComplianceEvidencePacket(TypedDict, total=False):
    id: str
    release_id: str
    state: str
    base_index: int
    waiver_credit_points: float
    completeness_index: float
    waiver_count: int
    waivers: List[dict]
    missing_items: List[str]
    sealed_at: Optional[str]
    sealed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only resources: id + created_at only (PRD §2.5)
# No ``updated_at`` and no ``version`` -- deliberately omitted below.
# ---------------------------------------------------------------------------


class ChangeDependency(TypedDict, total=False):
    id: str
    from_change_id: str
    to_change_id: str
    created_at: str


class Approval(TypedDict, total=False):
    id: str
    change_request_id: str
    kind: str
    decision: str
    approver_user_id: str
    note: Optional[str]
    pinned_risk_score: int
    pinned_change_version: int
    created_at: str


class ChangeFlagLink(TypedDict, total=False):
    id: str
    change_request_id: str
    feature_flag_id: str
    guard_kind: str
    created_at: str


class CanaryEvaluation(TypedDict, total=False):
    id: str
    deployment_id: str
    window_start_at: str
    window_end_at: str
    sample_count: int
    error_rate_pct_rounded: float
    latency_p95_ms: int
    weighted_health_score: float
    verdict: str
    abort_triggered: bool
    created_at: str


class HealthSignal(TypedDict, total=False):
    id: str
    deployment_id: str
    observed_at: str
    cohort: str
    request_count: int
    error_count: int
    latency_p95_ms: int
    created_at: str


#: Resource families, used by the shared assertion helpers.
FULL_QUARTET_ENTITIES = [
    "release_train",
    "environment",
    "release",
    "change_request",
    "feature_flag",
    "flag_rollout_step",
    "deployment",
    "incident",
    "release_note_document",
    "compliance_evidence_packet",
]

APPEND_ONLY_ENTITIES = [
    "change_dependency",
    "approval",
    "change_flag_link",
    "canary_evaluation",
    "health_signal",
]
