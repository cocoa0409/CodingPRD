"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    AUDIT_ADMIN = "AuditAdmin"
    CHIEF_AUDIT_EXECUTIVE = "ChiefAuditExecutive"
    AUDIT_COMMITTEE = "AuditCommittee"
    AUDIT_MANAGER = "AuditManager"
    FIELD_AUDITOR = "FieldAuditor"
    QUALITY_ASSESSOR = "QualityAssessor"
    MANAGEMENT_OWNER = "ManagementOwner"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------
class AuditableEntityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RiskAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class ScoringVariant(str, Enum):
    WEIGHTED = "WEIGHTED"
    CONSERVATIVE = "CONSERVATIVE"


class RiskTier(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RatingCriteriaConfigStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AuditPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"


class EngagementStatus(str, Enum):
    PLANNED = "PLANNED"
    SCOPED = "SCOPED"
    FIELDWORK = "FIELDWORK"
    REPORTING = "REPORTING"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AuditorGrade(str, Enum):
    STAFF = "STAFF"
    SENIOR = "SENIOR"
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"


class AuditorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentRole(str, Enum):
    LEAD = "LEAD"
    STAFF = "STAFF"
    REVIEWER = "REVIEWER"


class EngagementAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class WorkpaperStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    SIGNED_OFF = "SIGNED_OFF"
    RETURNED = "RETURNED"


class FindingStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_RESPONSE = "PENDING_RESPONSE"
    UNDER_REVIEW = "UNDER_REVIEW"
    AGREED = "AGREED"
    REBUTTED = "REBUTTED"
    ESCALATED = "ESCALATED"
    FINAL = "FINAL"


class FindingSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ManagementResponseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REBUTTED = "REBUTTED"


class ActionPlanStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED_FOR_VALIDATION = "SUBMITTED_FOR_VALIDATION"
    VALIDATED = "VALIDATED"


class ExtensionRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class AuditReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ISSUED = "ISSUED"
    DISTRIBUTED = "DISTRIBUTED"


class OverallConclusion(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    NEEDS_IMPROVEMENT = "NEEDS_IMPROVEMENT"
    UNSATISFACTORY = "UNSATISFACTORY"


class QAScope(str, Enum):
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class QAReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class QARating(str, Enum):
    PASS = "PASS"
    PASS_WITH_DEFICIENCIES = "PASS_WITH_DEFICIENCIES"
    FAIL = "FAIL"


class CommitteePackStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PRESENTED = "PRESENTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id/created_at/updated_at/version
# (PRD §2.4 common resource properties).
# ---------------------------------------------------------------------------
class AuditableEntity(TypedDict, total=False):
    id: str
    name: str
    business_owner: str
    regulatory_scrutiny: bool
    last_audit_completed_at: Optional[str]
    status: str
    retired_at: Optional[str]
    current_inherent_risk_score: Optional[int]
    current_risk_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RiskAssessment(TypedDict, total=False):
    id: str
    auditable_entity_id: str
    fiscal_year: int
    likelihood: int
    impact: int
    scoring_variant: str
    inherent_risk_score: int
    status: str
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RatingCriteriaConfig(TypedDict, total=False):
    id: str
    name: str
    critical_min: int
    high_min: int
    moderate_min: int
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditPlan(TypedDict, total=False):
    id: str
    fiscal_year: int
    title: str
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    engagement_count: int
    high_risk_coverage_pct: float
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    audit_plan_id: str
    auditable_entity_id: str
    supersedes_engagement_id: Optional[str]
    title: str
    scope_summary: str
    budget_hours: float
    start_date: str
    end_date: str
    status: str
    reserved_hours: float
    actual_hours: float
    provisional_hours: float
    signed_off_workpaper_count: int
    open_finding_count: int
    qa_regression_count: int
    priority_score: int
    utilization_final_pct: float
    utilization_provisional_pct: float
    created_at: str
    updated_at: str
    version: int


class Auditor(TypedDict, total=False):
    id: str
    full_name: str
    grade: str
    skills: Optional[List[str]]
    status: str
    created_at: str
    updated_at: str
    version: int


class EngagementAssignment(TypedDict, total=False):
    id: str
    engagement_id: str
    auditor_id: str
    role_in_engagement: str
    start_date: str
    end_date: str
    allocated_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Workpaper(TypedDict, total=False):
    id: str
    engagement_id: str
    reference: str
    title: str
    preparer_auditor_id: str
    reviewer_auditor_id: Optional[str]
    hours_worked: float
    status: str
    review_note: Optional[str]
    signed_off_at: Optional[str]
    locked: bool
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict, total=False):
    id: str
    engagement_id: str
    workpaper_id: Optional[str]
    rating_criteria_config_id: str
    title: str
    likelihood: int
    impact: int
    composite_score: int
    severity: str
    status: str
    negotiation_rounds: int
    created_by_user_id: str
    open_overdue_action_count: int
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ManagementResponse(TypedDict, total=False):
    id: str
    finding_id: str
    responder_user_id: str
    response_text: str
    proposed_due_date: str
    status: str
    reviewed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActionPlan(TypedDict, total=False):
    id: str
    finding_id: str
    description: str
    owner_name: str
    original_due_date: str
    due_date: str
    extension_count: int
    cumulative_extended_days: int
    status: str
    validated_by_user_id: Optional[str]
    validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExtensionRequest(TypedDict, total=False):
    id: str
    action_plan_id: str
    requested_due_date: str
    reason: str
    status: str
    decided_by_user_id: Optional[str]
    approved_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AuditReport(TypedDict, total=False):
    id: str
    engagement_id: str
    title: str
    overall_conclusion: Optional[str]
    status: str
    issued_at: Optional[str]
    distributed_at: Optional[str]
    distribution_list: Optional[List[str]]
    created_at: str
    updated_at: str
    version: int


class QAReview(TypedDict, total=False):
    id: str
    engagement_id: str
    scope: str
    assessor_auditor_id: Optional[str]
    doc_quality_score: Optional[int]
    fieldwork_quality_score: Optional[int]
    reporting_quality_score: Optional[int]
    independence_score: Optional[int]
    overall_score: Optional[float]
    rating: Optional[str]
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommitteePack(TypedDict, total=False):
    id: str
    audit_plan_id: str
    meeting_date: str
    title: str
    status: str
    snapshot_plan_completion_pct: Optional[float]
    snapshot_overdue_action_count: Optional[int]
    snapshot_critical_findings: Optional[int]
    snapshot_high_findings: Optional[int]
    is_stale_snapshot: bool
    finalized_at: Optional[str]
    presented_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
