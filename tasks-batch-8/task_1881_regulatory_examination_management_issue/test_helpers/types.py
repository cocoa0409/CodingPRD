"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REGULATORY_AFFAIRS_MANAGER = "RegulatoryAffairsManager"
    REMEDIATION_OWNER = "RemediationOwner"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    BOARD_REPORTER = "BoardReporter"


class Jurisdiction(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    FOREIGN = "FOREIGN"


class ExamType(str, Enum):
    SAFETY_SOUNDNESS = "SAFETY_SOUNDNESS"
    COMPLIANCE = "COMPLIANCE"
    IT = "IT"
    TRUST = "TRUST"
    SPECIALTY = "SPECIALTY"


class ExaminationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FIRST_DAY_ISSUED = "FIRST_DAY_ISSUED"
    FIELDWORK = "FIELDWORK"
    FINDINGS_DELIVERED = "FINDINGS_DELIVERED"
    REMEDIATION = "REMEDIATION"
    VALIDATION = "VALIDATION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ExamPosture(str, Enum):
    NORMAL = "NORMAL"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class FirstDayItemStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    WAIVED = "WAIVED"


class SubmissionQualityStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class MeetingStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class Severity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IssueClassification(str, Enum):
    MRA = "MRA"
    MRIA = "MRIA"


class IssueStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_PLANNED = "REMEDIATION_PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    VALIDATION_SUBMITTED = "VALIDATION_SUBMITTED"
    CLOSED = "CLOSED"
    OVERDUE = "OVERDUE"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    OVERDUE = "OVERDUE"


class EvidenceType(str, Enum):
    DOCUMENT_PACKAGE = "DOCUMENT_PACKAGE"
    TEST_RESULTS = "TEST_RESULTS"
    INTERNAL_AUDIT_REPORT = "INTERNAL_AUDIT_REPORT"
    THIRD_PARTY_ATTESTATION = "THIRD_PARTY_ATTESTATION"


class ReviewStatus(str, Enum):
    PENDING = "PENDING"
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class ClosureStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BoardReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class CertificationLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


# --- Entity payloads (common_fields entities carry id/created_at/updated_at/version) ---


class RegulatorAgency(TypedDict, total=False):
    id: str
    agency_code: str
    agency_name: str
    jurisdiction: str
    escalation_threshold_days: int
    repeat_finding_multiplier_bp: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Examination(TypedDict, total=False):
    id: str
    agency_id: str
    exam_cycle_code: str
    exam_type: str
    status: str
    scheduled_start_date: str
    scheduled_end_date: str
    first_day_letter_due_date: str
    posture: str
    repeat_finding_risk_score_bp: int
    overdue_item_count: int
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FirstDayLetterItem(TypedDict, total=False):
    id: str
    examination_id: str
    request_ref: str
    description: str
    due_date: str
    status: str
    submitted_at: Optional[str]
    waived_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DocumentSubmission(TypedDict, total=False):
    id: str
    first_day_item_id: str
    submission_round: int
    document_manifest: List[dict]
    quality_status: str
    quality_reject_reason: Optional[str]
    page_count_total: int
    created_at: str
    updated_at: str
    version: int


class ExaminerMeeting(TypedDict, total=False):
    id: str
    examination_id: str
    meeting_date: str
    attendees: List[str]
    minutes_summary: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InformalFinding(TypedDict, total=False):
    id: str
    examiner_meeting_id: str
    finding_text: str
    severity_hint: str
    promoted_issue_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Issue(TypedDict, total=False):
    id: str
    examination_id: str
    informal_finding_id: Optional[str]
    issue_ref: str
    classification: str
    severity: str
    is_repeat_finding: bool
    due_date: str
    status: str
    escalated_to_board: bool
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationPlan(TypedDict, total=False):
    id: str
    issue_id: str
    plan_version: int
    owner_user_id: str
    root_cause_narrative: str
    corrective_action_summary: str
    status: str
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationMilestone(TypedDict, total=False):
    id: str
    remediation_plan_id: str
    milestone_name: str
    sequence_index: int
    due_date: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ValidationEvidence(TypedDict, total=False):
    id: str
    issue_id: str
    evidence_type: str
    artifact_manifest: List[dict]
    submitted_by_user_id: str
    review_status: str
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClosureRequest(TypedDict, total=False):
    id: str
    issue_id: str
    request_round: int
    closure_narrative: str
    validation_evidence_id: str
    status: str
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoardReport(TypedDict, total=False):
    id: str
    examination_id: str
    reporting_period_start: str
    reporting_period_end: str
    open_issue_count: int
    overdue_issue_count: int
    escalated_issue_count: int
    total_repeat_finding_risk_bp: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitmentLogEntry(TypedDict, total=False):
    """Append-only record (PRD §2.4): carries only id + created_at plus its

    domain fields. No updated_at, no version.
    """

    id: str
    examination_id: str
    commitment_text: str
    committed_by_user_id: str
    committed_at: str
    due_date: str
    fulfilled_at: Optional[str]
    created_at: str


class BankOfficer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    officer_role_title: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class ComplianceReviewer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    certification_level: str
    active: bool
    created_at: str
    updated_at: str
    version: int
