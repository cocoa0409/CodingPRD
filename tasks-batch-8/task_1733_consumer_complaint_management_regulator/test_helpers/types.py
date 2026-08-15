"""Domain types: entity TypedDicts, status enums, role enum (PRD §2 and §3)."""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    INTAKE_SPECIALIST = "IntakeSpecialist"
    CASE_HANDLER = "CaseHandler"
    QA_REVIEWER = "QAReviewer"
    REMEDIATION_APPROVER = "RemediationApprover"
    EXECUTIVE_REVIEWER = "ExecutiveReviewer"
    COMPLAINT_MANAGER = "ComplaintManager"
    AUDITOR = "Auditor"


class ProductPosture(str, Enum):
    OPEN = "OPEN"
    WATCH = "WATCH"
    FROZEN = "FROZEN"


class ComplaintStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    RESPONSE_DRAFTED = "RESPONSE_DRAFTED"
    RESPONSE_QA = "RESPONSE_QA"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"
    WITHDRAWN = "WITHDRAWN"


class ReferralStatus(str, Enum):
    OPEN = "OPEN"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    CLOSED_BY_REGULATOR = "CLOSED_BY_REGULATOR"
    REOPENED_BY_REGULATOR = "REOPENED_BY_REGULATOR"


class ReferralTimeliness(str, Enum):
    PENDING = "PENDING"
    ON_TIME = "ON_TIME"
    LATE = "LATE"


class RcaStatus(str, Enum):
    DRAFT = "DRAFT"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"


class RcaVerdict(str, Enum):
    SUBSTANTIATED = "SUBSTANTIATED"
    NOT_SUBSTANTIATED = "NOT_SUBSTANTIATED"
    INCONCLUSIVE = "INCONCLUSIVE"


class RemediationDecisionType(str, Enum):
    NO_ACTION = "NO_ACTION"
    CORRECTION = "CORRECTION"
    RESTITUTION = "RESTITUTION"
    CORRECTION_AND_RESTITUTION = "CORRECTION_AND_RESTITUTION"


class RemediationDecisionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PAID = "PAID"
    REVERSED = "REVERSED"
    REJECTED = "REJECTED"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class QualityReviewStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QualityReviewOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EscalationTier(str, Enum):
    EXECUTIVE = "EXECUTIVE"
    LEGAL = "LEGAL"


class EscalationStatus(str, Enum):
    RAISED = "RAISED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    DISMISSED = "DISMISSED"


class IntakeEventType(str, Enum):
    CREATED = "CREATED"
    TAXONOMY_RECODED = "TAXONOMY_RECODED"
    STATUS_CHANGED = "STATUS_CHANGED"
    RESPONSE_DRAFTED = "RESPONSE_DRAFTED"
    QA_PASSED = "QA_PASSED"
    QA_FAILED = "QA_FAILED"
    REFERRAL_FILED = "REFERRAL_FILED"
    REFERRAL_RESPONDED = "REFERRAL_RESPONDED"
    REMEDIATION_APPROVED = "REMEDIATION_APPROVED"
    REMEDIATION_PAID = "REMEDIATION_PAID"
    REMEDIATION_REVERSED = "REMEDIATION_REVERSED"
    ESCALATED = "ESCALATED"
    ESCALATION_RESOLVED = "ESCALATION_RESOLVED"
    REOPENED = "REOPENED"
    WITHDRAWN = "WITHDRAWN"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Product, Channel, TaxonomyCategory, ResponseTemplate, Complaint,
# RegulatoryReferral, RootCauseAnalysis, RemediationDecision, QualityReview
# and EscalationCase carry the full common set (id, created_at, updated_at,
# version). IntakeEvent and TrendSnapshot are append-only / point-in-time
# records and carry ONLY id + created_at (PRD §2.4).
# ---------------------------------------------------------------------------


class Product(TypedDict, total=False):
    id: str
    product_code: str
    display_name: str
    posture: str
    open_complaint_count: int
    substantiated_count_90d: int
    early_warning_active: bool
    created_at: str
    updated_at: str
    version: int


class Channel(TypedDict, total=False):
    id: str
    channel_code: str
    display_name: str
    is_regulator_portal: bool
    created_at: str
    updated_at: str
    version: int


class TaxonomyCategory(TypedDict, total=False):
    id: str
    category_code: str
    parent_category_code: Optional[str]
    retired: bool
    created_at: str
    updated_at: str
    version: int


class ResponseTemplate(TypedDict, total=False):
    id: str
    template_key: str
    channel_code: str
    category_code: str
    body: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    complainant_ref: str
    channel_code: str
    product_code: str
    category_code: str
    received_at: str
    narrative: str
    claimed_loss_cents: int
    status: str
    response_text: Optional[str]
    response_template_key: Optional[str]
    resolved_at: Optional[str]
    approved_restitution_cents: int
    paid_restitution_cents: int
    days_open_business: int
    days_open_calendar: int
    timeliness_score: Optional[float]
    owner_user_id: str
    retention_purge_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntakeEvent(TypedDict, total=False):
    # Append-only audit record: id + created_at only (no updated_at/version).
    id: str
    complaint_id: str
    event_type: str
    actor_user_id: str
    actor_role: str
    payload: Any
    event_at: str
    created_at: str


class RegulatoryReferral(TypedDict, total=False):
    id: str
    complaint_id: str
    portal_ref: str
    received_via_portal_at: str
    response_due_at: str
    submitted_at: Optional[str]
    timeliness: str
    status: str
    response_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RootCauseAnalysis(TypedDict, total=False):
    id: str
    complaint_id: str
    verdict: str
    linked_product_code: str
    process_step: str
    completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RemediationDecision(TypedDict, total=False):
    id: str
    complaint_id: str
    decision_type: str
    line_items: List[dict]
    restitution_amount_cents: int
    drafted_by_user_id: str
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityReview(TypedDict, total=False):
    id: str
    complaint_id: str
    reviewer_user_id: str
    window_start_at: str
    window_end_at: str
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscalationCase(TypedDict, total=False):
    id: str
    complaint_id: str
    escalation_tier: str
    reason: str
    raised_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TrendSnapshot(TypedDict, total=False):
    # Point-in-time record: id + created_at only (no updated_at/version).
    id: str
    product_code: str
    period_start_at: str
    period_end_at: str
    complaint_count: int
    substantiated_count: int
    substantiation_rate_bps: int
    early_warning: bool
    evaluated_at: str
    created_at: str
