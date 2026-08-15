"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the common system-managed fields
(id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    COMPLIANCE_ADMIN = "ComplianceAdmin"
    HR_ADMIN = "HRAdmin"
    MANAGER = "Manager"
    EMPLOYEE = "Employee"
    AUDITOR = "Auditor"
    ANONYMOUS = "Anonymous"


class DeadlineMode(str, Enum):
    CALENDAR = "CALENDAR"
    BUSINESS_DAYS = "BUSINESS_DAYS"


class RegulatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class RoleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CurriculumStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class Recurrence(str, Enum):
    INITIAL_ONLY = "INITIAL_ONLY"
    VALIDITY_CYCLE = "VALIDITY_CYCLE"


class Criticality(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class EvidenceTier(str, Enum):
    NONE = "NONE"
    CERTIFICATE = "CERTIFICATE"
    PROCTORED_CERTIFICATE = "PROCTORED_CERTIFICATE"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class RoleChangeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"
    REVERSED = "REVERSED"


class ProgressStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    VERIFIED_COMPLETED = "VERIFIED_COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DeadlineStatus(str, Enum):
    ON_TRACK = "ON_TRACK"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"
    ESCALATED = "ESCALATED"
    FROZEN = "FROZEN"


class TriggerSource(str, Enum):
    NEW_HIRE = "NEW_HIRE"
    ROLE_CHANGE = "ROLE_CHANGE"
    REQUIREMENT_SWEEP = "REQUIREMENT_SWEEP"
    RECURRENCE = "RECURRENCE"
    MANUAL = "MANUAL"
    REVERSAL = "REVERSAL"


class ReviewStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    FINALIZED = "FINALIZED"


class AttestationStatus(str, Enum):
    PENDING = "PENDING"
    ATTESTED = "ATTESTED"
    EXCEPTION_PENDING = "EXCEPTION_PENDING"
    EXEMPTED = "EXEMPTED"
    EXPIRED = "EXPIRED"
    BLOCKED = "BLOCKED"


class ExceptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ExceptionReasonCode(str, Enum):
    MEDICAL_LEAVE = "MEDICAL_LEAVE"
    MILITARY_DUTY = "MILITARY_DUTY"
    ROLE_TRANSITION = "ROLE_TRANSITION"
    OTHER = "OTHER"


class NoticeKind(str, Enum):
    DUE_SOON_REMINDER = "DUE_SOON_REMINDER"
    OVERDUE_MANAGER = "OVERDUE_MANAGER"
    ESCALATION_COMPLIANCE = "ESCALATION_COMPLIANCE"


class NoticeStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class MetricVariant(str, Enum):
    STRICT = "STRICT"
    AUDIT_LENIENT = "AUDIT_LENIENT"


class Regulator(TypedDict, total=False):
    id: str
    code: str
    name: str
    deadline_mode: str
    recordkeeping_years: int
    escalation_interval_days: int
    reminder_days_before_due: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Role(TypedDict, total=False):
    id: str
    code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Curriculum(TypedDict, total=False):
    id: str
    regulator_id: str
    code: str
    title: str
    passing_score_pct: float
    validity_months: int
    max_attempts: int
    evidence_requirement: str
    recordkeeping_years_override: Optional[int]
    effective_recordkeeping_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CurriculumVersion(TypedDict, total=False):
    id: str
    curriculum_id: str
    version_no: int
    effective_from: str
    effective_to: Optional[str]
    content_uri: str
    created_at: str
    updated_at: str
    version: int


class RoleRequirement(TypedDict, total=False):
    id: str
    role_id: str
    curriculum_id: str
    recurrence: str
    due_in_days: int
    criticality: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    employee_no: str
    full_name: str
    hired_at: str
    manager_id: Optional[str]
    current_role_id: str
    status: str
    compliance_blocked: bool
    verified_completed_count: int
    created_at: str
    updated_at: str
    version: int


class EmployeeRoleChange(TypedDict, total=False):
    id: str
    employee_id: str
    from_role_code: str
    to_role_id: str
    effective_at: str
    status: str
    applied_at: Optional[str]
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict, total=False):
    id: str
    employee_id: str
    role_requirement_id: str
    curriculum_id: str
    trigger_source: str
    source_role_change_id: Optional[str]
    assigned_at: str
    base_due_at: str
    active_extension_days: int
    due_at: str
    attempts_used: int
    progress_status: str
    deadline_status: str
    completed_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompletionRecord(TypedDict, total=False):
    id: str
    assignment_id: str
    attempt_no: int
    score_pct: float
    evidence_type: str
    evidence_uri: Optional[str]
    submitted_at: str
    is_late: bool
    passed: bool
    review_status: str
    reviewed_by: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttestationCampaign(TypedDict, total=False):
    id: str
    year: int
    regulator_id: str
    window_open_at: str
    window_close_at: str
    statement_version: str
    status: str
    metrics: Optional[dict]
    created_at: str
    updated_at: str
    version: int


class Attestation(TypedDict, total=False):
    id: str
    campaign_id: str
    employee_id: str
    status: str
    attested_at: Optional[str]
    statement_version_snapshot: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttestationException(TypedDict, total=False):
    id: str
    attestation_id: str
    reason_code: str
    detail: str
    requested_by_manager_id: str
    status: str
    decided_by: Optional[str]
    decision_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EscalationNotice(TypedDict, total=False):
    id: str
    assignment_id: str
    level: int
    kind: str
    recipient_employee_id: Optional[str]
    triggered_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaveOfAbsence(TypedDict, total=False):
    id: str
    employee_id: str
    start_date: str
    end_date: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class AuditReport(TypedDict, total=False):
    id: str
    population_spec: dict
    metric_variant: str
    created_by: str
    generated_at: str
    metrics: dict
    recordkeeping_expires_at: str
    created_at: str
    updated_at: str
    version: int
