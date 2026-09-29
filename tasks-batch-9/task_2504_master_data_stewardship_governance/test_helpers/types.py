"""Domain types for the master data stewardship governance API.

Entity TypedDicts, status enums and the governance role enum, all named
exactly as the PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------


class UserRole(str, Enum):
    GOVERNANCE_ADMIN = "GovernanceAdmin"
    DATA_OWNER = "DataOwner"
    DATA_STEWARD = "DataSteward"
    CONSUMER_REP = "ConsumerRep"
    AUDITOR = "Auditor"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class DomainCode(str, Enum):
    CUSTOMER = "CUSTOMER"
    PRODUCT = "PRODUCT"
    VENDOR = "VENDOR"
    LOCATION = "LOCATION"


class DomainStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class GovernancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ClassificationLevel(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    RESTRICTED = "RESTRICTED"


class SourceSystemStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CERTIFIED = "CERTIFIED"
    DECERTIFIED = "DECERTIFIED"


class CertificationLevel(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    PRINCIPAL = "PRINCIPAL"


class SourceRegistrationRole(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    CONTRIBUTING = "CONTRIBUTING"
    CONSUMING = "CONSUMING"


class SourceRegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


class StewardRole(str, Enum):
    DATA_OWNER = "DATA_OWNER"
    DATA_STEWARD = "DATA_STEWARD"
    CUSTODIAN = "CUSTODIAN"


class StewardAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class QualityDimension(str, Enum):
    COMPLETENESS = "COMPLETENESS"
    VALIDITY = "VALIDITY"
    UNIQUENESS = "UNIQUENESS"
    TIMELINESS = "TIMELINESS"
    CONSISTENCY = "CONSISTENCY"


class RuleSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class QualityRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ScorecardBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


class FindingStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_PLANNED = "REMEDIATION_PLANNED"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class CurationStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    CURATED = "CURATED"
    MERGED_AWAY = "MERGED_AWAY"
    QUARANTINED = "QUARANTINED"


class PublicationStatus(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


class MatchConfidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class MergeProposalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MERGED = "MERGED"
    REJECTED = "REJECTED"
    REWORK = "REWORK"


class SurvivorshipVariant(str, Enum):
    SOURCE_PRIORITY = "SOURCE_PRIORITY"
    SCORE_PRIORITY = "SCORE_PRIORITY"


class ChangeType(str, Enum):
    REFERENCE_VALUE_ADD = "REFERENCE_VALUE_ADD"
    HIERARCHY_RESTRUCTURE = "HIERARCHY_RESTRUCTURE"
    CLASSIFICATION_UPLIFT = "CLASSIFICATION_UPLIFT"


class ChangeRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"
    WITHDRAWN = "WITHDRAWN"


class ChangeDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"


class MergeDecision(str, Enum):
    MERGE = "MERGE"
    REJECT = "REJECT"
    REWORK = "REWORK"


class Criticality(str, Enum):
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    TIER3 = "TIER3"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LineageStatus(str, Enum):
    UNDOCUMENTED = "UNDOCUMENTED"
    DOCUMENTED = "DOCUMENTED"
    STALE = "STALE"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------


class Domain(TypedDict):
    id: str
    code: str
    name: str
    status: str
    governance_posture: str
    classification_level: str
    sensitive_handling_required: bool
    authoritative_source_code: Optional[str]
    notification_lead_days_floor: int
    expected_attribute_count: int
    open_finding_weight: float
    quality_score_provisional: Optional[float]
    quality_score_certified: Optional[float]
    scorecard_run_seq: int
    reference_data_revision: int
    published_master_record_count: int
    scheduled_change_count: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SourceSystem(TypedDict):
    id: str
    code: str
    name: str
    trust_tier: int
    status: str
    certified_at: Optional[str]
    decertified_at: Optional[str]
    decertification_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Steward(TypedDict):
    id: str
    full_name: str
    email: str
    certification_level: str
    open_finding_load: int
    created_at: str
    updated_at: str
    version: int


class SourceRegistration(TypedDict):
    id: str
    domain_id: str
    source_system_id: str
    role: str
    trust_rank: int
    effective_from: str
    effective_to: Optional[str]
    status: str
    superseded_at: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StewardAssignment(TypedDict):
    id: str
    domain_id: str
    steward_id: str
    steward_role: str
    effective_from: str
    effective_to: Optional[str]
    status: str
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QualityRule(TypedDict):
    id: str
    domain_id: str
    owner_steward_id: str
    rule_code: str
    dimension: str
    weight_points: int
    threshold_pct: float
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScorecardRun(TypedDict):
    """A scorecard run is an immutable record: it carries an id and a
    created_at, and no updated_at or version."""

    id: str
    domain_id: str
    run_seq: int
    basis: str
    measured_at: str
    weighted_score: float
    rules_evaluated_count: int
    rules_failed_count: int
    findings_created_count: int
    posture_before: str
    posture_after: str
    posture_multiplier_applied: float
    created_at: str


class QualityFinding(TypedDict):
    id: str
    scorecard_run_id: str
    quality_rule_id: str
    status: str
    severity_weight: float
    measured_pct: float
    gap_pct: float
    assigned_steward_id: Optional[str]
    planned_by_steward_id: Optional[str]
    waived_by_steward_id: Optional[str]
    due_at: Optional[str]
    plan_note: Optional[str]
    resolution_note: Optional[str]
    waiver_justification: Optional[str]
    opened_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MasterRecord(TypedDict):
    id: str
    domain_id: str
    source_system_id: str
    natural_key: str
    attributes: Dict[str, Any]
    completeness_pct: float
    last_verified_at: str
    curation_status: str
    publication_status: str
    superseded_by_master_record_id: Optional[str]
    survivorship_score: float
    published_at: Optional[str]
    quarantine_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MergeProposal(TypedDict):
    id: str
    domain_id: str
    survivor_master_record_id: str
    duplicate_master_record_id: str
    proposer_steward_id: str
    reviewer_steward_id: Optional[str]
    name_similarity_pct: float
    key_overlap_pct: float
    match_score: float
    match_confidence: str
    status: str
    effective_survivor_master_record_id: Optional[str]
    survivor_swapped: bool
    survivorship_variant: Optional[str]
    survivorship_field_map: Optional[Dict[str, Any]]
    rework_count: int
    override_justification: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeRequest(TypedDict):
    id: str
    domain_id: str
    requester_steward_id: str
    reviewer_steward_id: Optional[str]
    change_type: str
    structural: bool
    title: str
    proposed_values: Dict[str, Any]
    status: str
    impact_consumer_count: int
    required_lead_days: int
    submitted_at: Optional[str]
    earliest_apply_at: Optional[str]
    scheduled_apply_at: Optional[str]
    freeze_window_start: Optional[str]
    freeze_window_end: Optional[str]
    revision_cycle_count: int
    applied_at: Optional[str]
    review_note: Optional[str]
    withdraw_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsumerSubscription(TypedDict):
    id: str
    domain_id: str
    consumer_code: str
    reporting_asset_key: str
    clearance_level: str
    criticality: str
    required_lead_days: int
    status: str
    lineage_path: Optional[List[str]]
    lineage_status: str
    lineage_revision: Optional[int]
    lineage_documented_at: Optional[str]
    pending_change_request_id: Optional[str]
    notified_at: Optional[str]
    acknowledged_at: Optional[str]
    acknowledged_revision: Optional[int]
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
