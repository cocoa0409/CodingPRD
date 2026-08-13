"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    HOTLINE_REPORTER = "HotlineReporter"
    INTAKE_SPECIALIST = "IntakeSpecialist"
    INVESTIGATOR = "Investigator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    AUDIT_COMMITTEE_MEMBER = "AuditCommitteeMember"
    ETHICS_PLATFORM_ADMIN = "EthicsPlatformAdmin"


class CaseStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    ASSIGNED = "ASSIGNED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    DETERMINATION_REVIEW = "DETERMINATION_REVIEW"
    REMEDIATION = "REMEDIATION"
    CLOSURE_READY = "CLOSURE_READY"
    MONITORING = "MONITORING"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFLICT_PENDING = "CONFLICT_PENDING"
    CLEARED = "CLEARED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class EvidenceStatus(str, Enum):
    PRESERVED = "PRESERVED"
    SEALED = "SEALED"
    EXCLUDED = "EXCLUDED"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"


class RemediationStatus(str, Enum):
    PROPOSED = "PROPOSED"
    IN_PROGRESS = "IN_PROGRESS"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    OVERDUE = "OVERDUE"


class FlagStatus(str, Enum):
    OPEN = "OPEN"
    DISMISSED = "DISMISSED"
    ESCALATED = "ESCALATED"


class MonitoringPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"


class NoticeStatus(str, Enum):
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PRESENTED = "PRESENTED"


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class CasePosture(str, Enum):
    NORMAL = "NORMAL"
    FROZEN = "FROZEN"


# ---------------- TypedDicts ----------------

class StaffMember(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    department: str
    capabilities: List[str]
    employment_status: str
    max_active_cases: int
    active_case_count: int
    weighted_caseload: int
    created_at: str
    updated_at: str
    version: int


class HotlineCase(TypedDict, total=False):
    id: str
    channel: str
    category: str
    confirmed_category: Optional[str]
    description: str
    region: str
    is_anonymous: bool
    subject_employee_ids: List[str]
    status: str
    posture: str
    severity: Optional[str]
    sla_days: Optional[int]
    triaged_by_id: Optional[str]
    assigned_investigator_id: Optional[str]
    duplicate_of_case_id: Optional[str]
    received_at: str
    closure_ready_at: Optional[str]
    closed_at: Optional[str]
    retaliation_risk_score: int
    reopen_count: int
    determination_finding: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CaseAssignment(TypedDict, total=False):
    id: str
    case_id: str
    investigator_id: str
    routed_by_id: str
    selection_mode: str
    status: str
    screened_by_id: Optional[str]
    conflict_type: Optional[str]
    waived_by_id: Optional[str]
    waiver_justification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict, total=False):
    id: str
    case_id: str
    investigator_id: str
    interviewee_role: str
    interviewee_identifier: str
    scheduled_start: str
    scheduled_end: str
    status: str
    summary: Optional[str]
    conducted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    case_id: str
    uploaded_by_id: str
    evidence_type: str
    description: str
    checksum: str
    captured_at: str
    status: str
    sealed_by_id: Optional[str]
    excluded_by_id: Optional[str]
    exclusion_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Determination(TypedDict, total=False):
    id: str
    case_id: str
    finding: str
    rationale: str
    decided_by_id: str
    reviewed_by_id: Optional[str]
    status: str
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemediationAction(TypedDict, total=False):
    id: str
    case_id: str
    determination_id: str
    action_type: str
    owner_department: str
    description: str
    due_date: str
    status: str
    created_by_id: str
    verified_by_id: Optional[str]
    extension_count: int
    created_at: str
    updated_at: str
    version: int


class RetaliationFlag(TypedDict, total=False):
    id: str
    case_id: str
    reported_via: str
    description: str
    weight: int
    flagged_at: str
    status: str
    dismissed_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringPlan(TypedDict, total=False):
    id: str
    case_id: str
    start_at: str
    end_at: str
    check_in_interval_days: int
    next_check_in_due: Optional[str]
    last_check_in_at: Optional[str]
    missed_checkin_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CaseClosureNotice(TypedDict, total=False):
    # common_fields: false — append-only; only id + created_at guaranteed
    id: str
    case_id: str
    closure_summary: str
    status: str
    sent_at: str
    acknowledged_at: Optional[str]
    created_at: str


class LegalHold(TypedDict, total=False):
    id: str
    case_id: str
    start_at: str
    end_at: str
    reason: str
    status: str
    placed_by_id: str
    released_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AuditCommitteeReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    status: str
    total_received: int
    total_closures: int
    avg_days_to_close_calendar: Optional[float]
    avg_days_to_close_hold_adjusted: Optional[float]
    org_substantiation_rate: Optional[float]
    pooled_substantiation_rate: Optional[float]
    overdue_remediation_count: int
    retaliation_escalation_count: int
    generated_by_id: str
    created_at: str
    updated_at: str
    version: int


class CaseStatusEvent(TypedDict, total=False):
    # common_fields: false — append-only; only id + created_at guaranteed
    id: str
    case_id: str
    event_type: str
    from_status: Optional[str]
    to_status: Optional[str]
    actor_role: str
    actor_id: str
    occurred_at: str
    created_at: str
