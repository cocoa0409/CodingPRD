"""Domain types for the DR Failover Exercise API: enums and entity shapes."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    RESILIENCE_COORDINATOR = "ResilienceCoordinator"
    BUSINESS_OWNER = "BusinessOwner"
    IT_OPERATOR = "ITOperator"
    RISK_APPROVER = "RiskApprover"
    AUDIT_LIAISON = "AuditLiaison"
    PLATFORM_ADMIN = "PlatformAdmin"


class OrgRole(str, Enum):
    BUSINESS_OWNER = "BUSINESS_OWNER"
    RESILIENCE_COORDINATOR = "RESILIENCE_COORDINATOR"
    IT_OPERATOR = "IT_OPERATOR"
    RISK_APPROVER = "RISK_APPROVER"
    AUDIT_LIAISON = "AUDIT_LIAISON"


class ApprovalAuthorityLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class StakeholderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SiteRole(str, Enum):
    PRIMARY = "PRIMARY"
    RECOVERY = "RECOVERY"


class TierAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    TIER_PROPOSED = "TIER_PROPOSED"
    AGREED = "AGREED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


class ApplicationTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class AssetKind(str, Enum):
    DATA_STORE = "DATA_STORE"
    INFRA_COMPONENT = "INFRA_COMPONENT"


class ReplicationMode(str, Enum):
    SYNCHRONOUS = "SYNCHRONOUS"
    ASYNCHRONOUS = "ASYNCHRONOUS"
    BATCH_SNAPSHOT = "BATCH_SNAPSHOT"


class NodeKind(str, Enum):
    APPLICATION = "APPLICATION"
    ASSET = "ASSET"


class EdgeKind(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class GroupPosture(str, Enum):
    READY = "READY"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PostureReason(str, Enum):
    READY_ALL_CHECKS_PASSED = "READY_ALL_CHECKS_PASSED"
    NO_VALIDATED_RUNBOOK = "NO_VALIDATED_RUNBOOK"
    RUNBOOK_STALE = "RUNBOOK_STALE"
    OPEN_CRITICAL_FINDING = "OPEN_CRITICAL_FINDING"


class RunbookStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    VALIDATED = "VALIDATED"
    STALE = "STALE"
    SUPERSEDED = "SUPERSEDED"


class RunbookStaleReason(str, Enum):
    NONE = "NONE"
    APPLICATION_RETIERED = "APPLICATION_RETIERED"
    STEP_OWNER_SUSPENDED = "STEP_OWNER_SUSPENDED"
    SUPERSEDED_BY_REVISION = "SUPERSEDED_BY_REVISION"


class StepValidationStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATED = "VALIDATED"
    INVALIDATED = "INVALIDATED"


class ExerciseType(str, Enum):
    TABLETOP = "TABLETOP"
    COMPONENT_FAILOVER = "COMPONENT_FAILOVER"
    FULL_SITE_FAILOVER = "FULL_SITE_FAILOVER"


class ExecutionState(str, Enum):
    DRAFT = "DRAFT"
    SCOPED = "SCOPED"
    PENDING_IMPACT_APPROVAL = "PENDING_IMPACT_APPROVAL"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_EXECUTION = "IN_EXECUTION"
    FAILOVER_COMPLETE = "FAILOVER_COMPLETE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    ABORTED = "ABORTED"


class DataState(str, Enum):
    DATA_NOT_STARTED = "DATA_NOT_STARTED"
    DATA_VALIDATING = "DATA_VALIDATING"
    DATA_VERIFIED = "DATA_VERIFIED"
    DATA_DIVERGENT = "DATA_DIVERGENT"
    DATA_RECONCILING = "DATA_RECONCILING"


class FailbackState(str, Enum):
    FAILBACK_NOT_PLANNED = "FAILBACK_NOT_PLANNED"
    FAILBACK_PLANNED = "FAILBACK_PLANNED"
    SYNC_IN_PROGRESS = "SYNC_IN_PROGRESS"
    SYNC_FAILED = "SYNC_FAILED"
    FAILBACK_COMPLETE = "FAILBACK_COMPLETE"


class ClosureReason(str, Enum):
    NONE = "NONE"
    CLOSED_NORMALLY = "CLOSED_NORMALLY"
    ABORTED_IN_EXECUTION = "ABORTED_IN_EXECUTION"
    CANCELLED_BY_COORDINATOR = "CANCELLED_BY_COORDINATOR"
    CANCELLED_GROUP_FROZEN = "CANCELLED_GROUP_FROZEN"


class StepOutcome(str, Enum):
    PASSED = "PASSED"
    PASSED_WITH_ISSUE = "PASSED_WITH_ISSUE"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class FindingState(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_ASSIGNED = "REMEDIATION_ASSIGNED"
    REMEDIATED = "REMEDIATED"
    RETEST_SCHEDULED = "RETEST_SCHEDULED"
    RETEST_FAILED = "RETEST_FAILED"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class EvidenceState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    SIGNED_OFF = "SIGNED_OFF"
    SEALED = "SEALED"


class EvidenceReturnReason(str, Enum):
    NONE = "NONE"
    INCOMPLETE_MANIFEST = "INCOMPLETE_MANIFEST"


# --- Entity shapes -----------------------------------------------------------
# Every entity below carries id, created_at, updated_at and version, except
# ReplicationObservation, which is an append-only log row carrying only
# id and created_at.


class Stakeholder(TypedDict):
    id: str
    full_name: str
    email: str
    org_roles: List[str]
    approval_authority_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Site(TypedDict):
    id: str
    name: str
    site_code: str
    role: str
    usable_capacity_units: int
    reserved_capacity_units: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    name: str
    app_code: str
    business_owner_id: str
    primary_site_id: str
    criticality_weight: int
    recovery_group_id: Optional[str]
    tier_agreement_status: str
    proposed_tier: Optional[str]
    proposed_rto_minutes: Optional[int]
    proposed_rpo_minutes: Optional[int]
    proposed_by_id: Optional[str]
    rationale: Optional[str]
    tier: Optional[str]
    rto_minutes: Optional[int]
    rpo_minutes: Optional[int]
    retier_count: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    name: str
    asset_code: str
    asset_kind: str
    site_id: str
    replication_mode: str
    restore_minutes: int
    expected_txn_rate_per_minute: int
    recovery_group_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReplicationObservation(TypedDict):
    id: str
    asset_id: str
    observed_at: str
    replication_lag_seconds: int
    unreplicated_txn_count: int
    recorded_by_user_id: str
    created_at: str


class DependencyEdge(TypedDict):
    id: str
    from_node_kind: str
    from_node_id: str
    to_node_kind: str
    to_node_id: str
    edge_kind: str
    created_at: str
    updated_at: str
    version: int


class RecoveryGroup(TypedDict):
    id: str
    name: str
    group_code: str
    recovery_site_id: str
    lead_coordinator_id: str
    recovery_order: int
    posture: str
    posture_reason: str
    projected_recovery_minutes: int
    recovery_sequence: List[str]
    open_finding_count: int
    current_runbook_id: Optional[str]
    change_freeze_start_at: Optional[str]
    change_freeze_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Runbook(TypedDict):
    id: str
    recovery_group_id: str
    title: str
    author_id: str
    revision: int
    status: str
    readiness_score: float
    stale_reason: str
    validity_days: int
    validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RunbookStep(TypedDict):
    id: str
    runbook_id: str
    step_number: int
    description: str
    owner_id: str
    expected_minutes: int
    weight: int
    covers_application_id: Optional[str]
    covers_asset_id: Optional[str]
    validation_status: str
    last_validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Exercise(TypedDict):
    id: str
    name: str
    exercise_type: str
    recovery_site_id: str
    coordinator_id: str
    planned_start_at: str
    planned_end_at: str
    execution_state: str
    data_state: str
    failback_state: str
    closure_reason: str
    required_capacity_units: int
    provisional_impact_score: Optional[float]
    production_impact_score: Optional[float]
    required_approval_level: Optional[str]
    impact_approved_by_id: Optional[str]
    rto_objective_minutes: Optional[int]
    rpo_objective_minutes: Optional[int]
    achieved_rto_minutes: Optional[int]
    achieved_rpo_minutes: Optional[int]
    rto_met: Optional[bool]
    rpo_met: Optional[bool]
    execution_started_at: Optional[str]
    failover_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExerciseScopeItem(TypedDict):
    id: str
    exercise_id: str
    recovery_group_id: str
    runbook_id_snapshot: str
    group_projected_recovery_minutes_snapshot: int
    capacity_units_contributed: int
    created_at: str
    updated_at: str
    version: int


class StepExecution(TypedDict):
    id: str
    exercise_id: str
    runbook_step_id: str
    outcome: str
    elapsed_seconds: int
    elapsed_minutes: int
    performed_by_user_id: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict):
    id: str
    exercise_id: str
    recovery_group_id: str
    severity: str
    title: str
    description: str
    due_at: Optional[str]
    state: str
    owner_id: Optional[str]
    retest_exercise_id: Optional[str]
    retest_failure_count: int
    escalated: bool
    created_at: str
    updated_at: str
    version: int


class EvidencePackage(TypedDict):
    id: str
    exercise_id: str
    prepared_by_id: str
    state: str
    manifest_line_count: int
    return_reason: str
    signed_off_by_id: Optional[str]
    sealed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
