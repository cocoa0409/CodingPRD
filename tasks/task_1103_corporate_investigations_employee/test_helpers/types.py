"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class CaseStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    PLANNING = "PLANNING"
    FIELDWORK = "FIELDWORK"
    FINDINGS = "FINDINGS"
    DISPOSITION = "DISPOSITION"
    REMEDIATION = "REMEDIATION"
    CLOSED = "CLOSED"
    DISMISSED = "DISMISSED"


class AllegationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    LINKED = "LINKED"
    DISMISSED = "DISMISSED"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SubjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"
    SEPARATED = "SEPARATED"


class NoticeStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RELEASED = "RELEASED"


class ScopeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    IN_PROGRESS = "IN_PROGRESS"
    COLLECTED = "COLLECTED"
    WITHDRAWN = "WITHDRAWN"


class EvidenceStatus(str, Enum):
    LOGGED = "LOGGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADMITTED = "ADMITTED"
    EXCLUDED = "EXCLUDED"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    UPJOHN_DELIVERED = "UPJOHN_DELIVERED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class DesignationStatus(str, Enum):
    DESIGNATED = "DESIGNATED"
    CONFIRMED = "CONFIRMED"
    CHALLENGED = "CHALLENGED"
    WAIVED = "WAIVED"


class FindingStatus(str, Enum):
    DRAFT = "DRAFT"
    CALIBRATED = "CALIBRATED"
    FINAL = "FINAL"
    CHALLENGED = "CHALLENGED"


class RecommendationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    LEGAL_REVIEW = "LEGAL_REVIEW"
    DISTRIBUTION_APPROVED = "DISTRIBUTION_APPROVED"
    DISTRIBUTED = "DISTRIBUTED"
    RECALLED = "RECALLED"
    SUPERSEDED = "SUPERSEDED"


class DisclosureStatus(str, Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"
    FILED = "FILED"
    OVERRIDDEN = "OVERRIDDEN"
    SUPERSEDED = "SUPERSEDED"


class RemediationStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_VERIFICATION = "AWAITING_VERIFICATION"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    DISMISSED = "DISMISSED"


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    INVESTIGATOR = "Investigator"
    INVESTIGATIONS_MANAGER = "InvestigationsManager"
    HR_BUSINESS_PARTNER = "HRBusinessPartner"
    GENERAL_COUNSEL = "GeneralCounsel"
    CHIEF_LEGAL_OFFICER = "ChiefLegalOfficer"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    SYSTEM_ADMIN = "SystemAdmin"


class Case(TypedDict, total=False):
    id: str
    title: str
    description: Optional[str]
    allegation_category: str
    severity: str
    department: Optional[str]
    lead_investigator_id: str
    case_number: str
    status: str
    pattern_escalated: bool
    case_priority_score: int
    priority_tier: str
    preservation_completeness_ratio: float
    active_privileged_artifact_count: int
    open_remediation_count: int
    created_at: str
    updated_at: str
    version: int


class Allegation(TypedDict, total=False):
    id: str
    case_id: str
    reporter_channel: str
    reporter_ref: Optional[str]
    is_anonymous: bool
    narrative: str
    occurred_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InvestigationPlan(TypedDict, total=False):
    id: str
    case_id: str
    plan_version: int
    scope_statement: str
    planned_start: str
    planned_end: str
    drafter_id: str
    status: str
    rejection_reason: Optional[str]
    approved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseSubject(TypedDict, total=False):
    id: str
    case_id: str
    employee_ref: str
    role_in_case: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PreservationNotice(TypedDict, total=False):
    id: str
    case_id: str
    custodian_ref: str
    scope: str
    is_regulator_ordered: bool
    issued_at: str
    acknowledged_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CollectionScope(TypedDict, total=False):
    id: str
    case_id: str
    preservation_notice_id: Optional[str]
    custodian_ref: str
    data_source: str
    planned_start: str
    planned_end: str
    collected_item_count: int
    collected_bytes: int
    review_effort_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    collection_scope_id: str
    case_id: str
    custodian_ref: str
    hash_value: str
    size_bytes: int
    captured_at: str
    description: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WitnessInterview(TypedDict, total=False):
    id: str
    case_id: str
    witness_ref: str
    interviewer_id: str
    is_subject_interview: bool
    scheduled_start: str
    scheduled_end: str
    room_ref: Optional[str]
    upjohn_delivered_at: Optional[str]
    completed_at: Optional[str]
    completion_note: Optional[str]
    no_show_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PrivilegeDesignation(TypedDict, total=False):
    id: str
    case_id: str
    target_type: str
    target_id: str
    privilege_type: str
    rationale: Optional[str]
    designated_by: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Finding(TypedDict, total=False):
    id: str
    case_id: str
    allegation_id: str
    subject_id: str
    evidence_item_ids: List[str]
    consistency_level: Optional[str]
    subject_admission: Optional[bool]
    finding_type: Optional[str]
    substantiation_score_provisional: float
    substantiation_score_final: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class DisciplinaryRecommendation(TypedDict, total=False):
    id: str
    finding_id: str
    proposed_by: str
    severity_assessment: str
    prior_history_count: int
    mitigation_count: int
    aggravation_count: int
    index_policy_matrix: int
    index_calibrated: int
    suggested_action: str
    recommended_action: str
    justification: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CaseReport(TypedDict, total=False):
    id: str
    case_id: str
    title: str
    distribution_tier: str
    distribution_list: List[str]
    report_privilege_type: str
    pinned_designation_snapshot: Optional[List[str]]
    distributed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SelfDisclosureDecision(TypedDict, total=False):
    id: str
    case_id: str
    regulator: str
    decision_deadline: str
    decision: Optional[str]
    rationale: Optional[str]
    decided_by: Optional[str]
    decided_at: Optional[str]
    filed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RemediationAction(TypedDict, total=False):
    id: str
    case_id: str
    action_type: str
    owner_ref: str
    description: str
    due_date: str
    is_overdue: bool
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PatternAlert(TypedDict, total=False):
    id: str
    alert_type: str
    alert_key: str
    window_start: str
    window_end: str
    case_ids: List[str]
    pattern_risk_score: float
    risk_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int
