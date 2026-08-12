"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD entity catalogue. Entities with the full common-field
set carry id + created_at + updated_at + version; append-only entities
(ConcentrationBucket, AuditFinding, RiskTierChangeLog) carry only id + created_at.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    VENDOR_RELATIONSHIP_MANAGER = "VendorRelationshipManager"
    RISK_OFFICER = "RiskOfficer"
    BUSINESS_UNIT_OWNER = "BusinessUnitOwner"
    INTERNAL_AUDITOR = "InternalAuditor"
    COMPLIANCE_DIRECTOR = "ComplianceDirector"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status / field enums (PRD §2.9)
# ---------------------------------------------------------------------------

class VendorStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITED = "EXITED"


class TierPosture(str, Enum):
    CLEAN = "CLEAN"
    WATCH = "WATCH"
    ESCALATED = "ESCALATED"
    BREACH = "BREACH"


class CriticalityTier(str, Enum):
    TIER_1_CRITICAL = "TIER_1_CRITICAL"
    TIER_2_HIGH = "TIER_2_HIGH"
    TIER_3_STANDARD = "TIER_3_STANDARD"
    TIER_4_LOW = "TIER_4_LOW"


class HeadquartersRegion(str, Enum):
    NA = "NA"
    EMEA = "EMEA"
    APAC = "APAC"
    LATAM = "LATAM"


class ServiceCategory(str, Enum):
    CLOUD_INFRA = "CLOUD_INFRA"
    PAYMENTS = "PAYMENTS"
    KYC_AML = "KYC_AML"
    DATA_ANALYTICS = "DATA_ANALYTICS"
    CUSTODIAL = "CUSTODIAL"
    BPO = "BPO"
    LEGAL = "LEGAL"
    OTHER = "OTHER"


class EngagementLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    DD_IN_PROGRESS = "DD_IN_PROGRESS"
    DD_APPROVED = "DD_APPROVED"
    CONTRACTING = "CONTRACTING"
    ACTIVE = "ACTIVE"
    EXITING = "EXITING"
    EXITED = "EXITED"
    TERMINATED_FOR_CAUSE = "TERMINATED_FOR_CAUSE"


class RiskAttentionState(str, Enum):
    NORMAL = "NORMAL"
    UNDER_REVIEW = "UNDER_REVIEW"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"


class DataSensitivity(str, Enum):
    PUBLIC = "PUBLIC"
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    REGULATED = "REGULATED"


class DDPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class DDOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AcknowledgementStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"


class DataAccessLevel(str, Enum):
    NONE = "NONE"
    METADATA = "METADATA"
    PII = "PII"
    REGULATED_PII = "REGULATED_PII"


class MonitoringCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED_ON_TIME = "COMPLETED_ON_TIME"
    COMPLETED_LATE = "COMPLETED_LATE"
    OVERDUE = "OVERDUE"
    WAIVED = "WAIVED"


class IncidentType(str, Enum):
    DATA_BREACH = "DATA_BREACH"
    SLA_BREACH = "SLA_BREACH"
    OUTAGE = "OUTAGE"
    FINANCIAL_DISTRESS = "FINANCIAL_DISTRESS"
    REGULATORY_FINDING = "REGULATORY_FINDING"
    FOURTH_PARTY_EVENT = "FOURTH_PARTY_EVENT"


class Severity(str, Enum):
    SEV_1 = "SEV_1"
    SEV_2 = "SEV_2"
    SEV_3 = "SEV_3"
    SEV_4 = "SEV_4"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    REMEDIATION_PLANNED = "REMEDIATION_PLANNED"
    REMEDIATION_IN_PROGRESS = "REMEDIATION_IN_PROGRESS"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class RemediationPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    IN_EXECUTION = "IN_EXECUTION"
    VERIFICATION_SUBMITTED = "VERIFICATION_SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AssessmentStatus(str, Enum):
    COMPUTING = "COMPUTING"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class GroupingDimension(str, Enum):
    REGION = "REGION"
    SERVICE_CATEGORY = "SERVICE_CATEGORY"


class BCPTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BCPOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class BCPScenario(str, Enum):
    FULL_FAILOVER = "FULL_FAILOVER"
    PARTIAL_DEGRADATION = "PARTIAL_DEGRADATION"
    CYBER_INCIDENT = "CYBER_INCIDENT"
    DATA_RESTORE = "DATA_RESTORE"


class AuditScope(str, Enum):
    SECURITY = "SECURITY"
    FINANCIAL = "FINANCIAL"
    OPERATIONAL = "OPERATIONAL"
    REGULATORY = "REGULATORY"
    FULL = "FULL"


class AuditStatus(str, Enum):
    INITIATED = "INITIATED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED = "CLOSED"


class BoardReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — full common-field entities (id, created_at, updated_at,
# version)
# ---------------------------------------------------------------------------

class Vendor(TypedDict, total=False):
    id: str
    legal_name: str
    headquarters_region: str
    service_category: str
    criticality_tier: str
    status: str
    tier_posture: str
    composite_risk_score: float
    onboarded_by_user_id: str
    archived_at: Optional[str]
    next_monitoring_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VendorEngagement(TypedDict, total=False):
    id: str
    vendor_id: str
    engagement_code: str
    service_summary: str
    annual_spend_cents: int
    data_sensitivity: str
    lifecycle_status: str
    risk_attention_state: str
    started_by_user_id: str
    exit_readiness_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class DueDiligencePackage(TypedDict, total=False):
    id: str
    engagement_id: str
    financial_review_score: int
    security_review_score: int
    compliance_review_score: int
    financial_reviewer_id: str
    security_reviewer_id: str
    compliance_reviewer_id: str
    aggregate_dd_score: float
    dd_outcome: str
    status: str
    submitted_by_user_id: Optional[str]
    approver_user_id: Optional[str]
    review_round: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    engagement_id: str
    contract_reference: str
    effective_date: str
    expiry_date: str
    has_right_to_audit_clause: bool
    has_sla_terms: bool
    has_exit_plan_section: bool
    sla_uptime_pct: float
    breach_cure_window_days: int
    renewal_notice_days: int
    status: str
    version_pin_dd_package_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FourthParty(TypedDict, total=False):
    id: str
    engagement_id: str
    name: str
    service_provided: str
    parent_fourth_party_id: Optional[str]
    data_access_level: str
    acknowledgement_status: str
    acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringCycle(TypedDict, total=False):
    id: str
    vendor_id: str
    cycle_index: int
    due_at: str
    cadence_days: int
    status: str
    completed_at: Optional[str]
    findings_summary: Optional[str]
    waived_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    engagement_id: str
    incident_type: str
    severity: str
    detected_at: str
    reported_by_user_id: str
    status: str
    remediation_due_at: Optional[str]
    closed_at: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict, total=False):
    id: str
    incident_id: str
    plan_summary: str
    committed_completion_date: str
    owner_user_id: str
    verification_evidence_uri: Optional[str]
    status: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConcentrationAssessment(TypedDict, total=False):
    id: str
    assessment_window_start: str
    assessment_window_end: str
    grouping_dimension: str
    status: str
    computed_at: Optional[str]
    published_by_user_id: Optional[str]
    breach_bucket_keys: List[str]
    created_at: str
    updated_at: str
    version: int


class BusinessContinuityTest(TypedDict, total=False):
    id: str
    engagement_id: str
    scheduled_for: str
    scenario: str
    rto_target_minutes: int
    rpo_target_minutes: int
    actual_rto_minutes: Optional[int]
    actual_rpo_minutes: Optional[int]
    status: str
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditExercise(TypedDict, total=False):
    id: str
    engagement_id: str
    scope: str
    exercised_by_user_id: str
    initiated_at: str
    findings_count: int
    status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoardReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    status: str
    snapshot_payload: Optional[Dict[str, Any]]
    published_at: Optional[str]
    published_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — ONLY id + created_at (no updated_at, no version)
# ---------------------------------------------------------------------------

class ConcentrationBucket(TypedDict, total=False):
    id: str
    assessment_id: str
    bucket_key: str
    total_spend_cents: int
    share_pct: float
    is_breach: bool
    created_at: str


class AuditFinding(TypedDict, total=False):
    id: str
    audit_exercise_id: str
    severity: str
    description: str
    raised_incident_id: Optional[str]
    created_at: str


class RiskTierChangeLog(TypedDict, total=False):
    id: str
    vendor_id: str
    from_tier: str
    to_tier: str
    reason: str
    changed_by_user_id: str
    created_at: str
