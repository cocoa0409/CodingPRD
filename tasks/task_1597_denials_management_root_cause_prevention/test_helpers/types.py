"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    DENIALS_SPECIALIST = "DenialsSpecialist"
    DENIALS_MANAGER = "DenialsManager"
    REVENUE_CYCLE_DIRECTOR = "RevenueCycleDirector"
    UPSTREAM_OWNER = "UpstreamOwner"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"


class PayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class PlanType(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    MANAGED_CARE = "MANAGED_CARE"


class DenialCategory(str, Enum):
    REGISTRATION = "REGISTRATION"
    AUTHORIZATION = "AUTHORIZATION"
    CODING = "CODING"
    CLINICAL_DOCUMENTATION = "CLINICAL_DOCUMENTATION"
    BILLING = "BILLING"
    CONTRACTUAL = "CONTRACTUAL"


class Department(str, Enum):
    REGISTRATION = "REGISTRATION"
    AUTHORIZATION = "AUTHORIZATION"
    CODING = "CODING"


class DenialStatus(str, Enum):
    RECEIVED = "RECEIVED"
    TRIAGED = "TRIAGED"
    QUEUED = "QUEUED"
    IN_APPEAL = "IN_APPEAL"
    RESOLVED_PAID = "RESOLVED_PAID"
    RESOLVED_WRITTEN_OFF = "RESOLVED_WRITTEN_OFF"
    CLOSED_EXHAUSTED = "CLOSED_EXHAUSTED"
    CLOSED_EXPIRED = "CLOSED_EXPIRED"


class QueueBucket(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AppealStatus(str, Enum):
    DRAFT = "DRAFT"
    LETTER_GENERATED = "LETTER_GENERATED"
    SUBMITTED = "SUBMITTED"
    OVERTURNED = "OVERTURNED"
    PARTIALLY_OVERTURNED = "PARTIALLY_OVERTURNED"
    UPHELD = "UPHELD"
    WITHDRAWN = "WITHDRAWN"


class AttachmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class DocumentType(str, Enum):
    CLINICAL_NOTES = "CLINICAL_NOTES"
    PHYSICIAN_LETTER = "PHYSICIAN_LETTER"
    LAB_RESULTS = "LAB_RESULTS"
    AUTH_RECORD = "AUTH_RECORD"
    ITEMIZED_BILL = "ITEMIZED_BILL"
    REMITTANCE_COPY = "REMITTANCE_COPY"


class TaskStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FIX_IMPLEMENTED = "FIX_IMPLEMENTED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class TaskType(str, Enum):
    PROCESS_FIX = "PROCESS_FIX"
    TRAINING = "TRAINING"
    SYSTEM_CONFIG = "SYSTEM_CONFIG"
    DATA_QUALITY = "DATA_QUALITY"


class WriteOffStatus(str, Enum):
    PENDING_MANAGER = "PENDING_MANAGER"
    ESCALATED_DIRECTOR = "ESCALATED_DIRECTOR"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RESCINDED = "RESCINDED"


class ApprovalTier(str, Enum):
    STANDARD = "STANDARD"
    ESCALATED = "ESCALATED"


class WriteOffReason(str, Enum):
    TIMELY_FILING_EXPIRED = "TIMELY_FILING_EXPIRED"
    SMALL_BALANCE = "SMALL_BALANCE"
    APPEALS_EXHAUSTED = "APPEALS_EXHAUSTED"
    CONTRACTUAL_ADJUSTMENT = "CONTRACTUAL_ADJUSTMENT"
    OTHER = "OTHER"


class ScorecardStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class ScoreTier(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    WATCH = "WATCH"
    CRITICAL = "CRITICAL"


class ProgramStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class Outcome(str, Enum):
    OVERTURNED = "OVERTURNED"
    PARTIALLY_OVERTURNED = "PARTIALLY_OVERTURNED"
    UPHELD = "UPHELD"


class Payer(TypedDict, total=False):
    id: str
    name: str
    plan_type: str
    default_timely_filing_days: int
    status: str
    appeal_policy_review_required: bool
    created_at: str
    updated_at: str
    version: int


class PayerAppealPolicy(TypedDict, total=False):
    id: str
    payer_id: str
    level_number: int
    timely_filing_days: int
    response_window_days: int
    required_attachment_types: list
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RemittanceCode(TypedDict, total=False):
    id: str
    code: str
    category: str
    default_department: str
    appealable: bool
    description: str
    created_at: str
    updated_at: str
    version: int


class DenialCase(TypedDict, total=False):
    id: str
    claim_number: str
    patient_account_number: str
    payer_id: str
    remittance_code_id: str
    category: str
    billed_amount_cents: int
    denied_amount_cents: int
    service_date: str
    remittance_received_date: str
    status: str
    root_cause_department: Optional[str]
    preventable_flag: bool
    current_appeal_level: int
    assigned_specialist_id: Optional[str]
    recovered_amount_cents: int
    written_off_cents: int
    open_balance_cents: int
    next_appeal_deadline: Optional[str]
    priority_score: float
    queue_bucket: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    denial_case_id: str
    previous_appeal_id: Optional[str]
    level_number: int
    status: str
    letter_body: Optional[str]
    generated_at: Optional[str]
    submitted_at: Optional[str]
    response_due_date: Optional[str]
    outcome_recorded_at: Optional[str]
    outcome_amount_cents: int
    payer_response_code: str
    reversal_reason: str
    created_at: str
    updated_at: str
    version: int


class AppealAttachment(TypedDict, total=False):
    id: str
    appeal_id: str
    document_type: str
    file_reference: str
    status: str
    voided_reason: str
    created_at: str
    updated_at: str
    version: int


class RootCauseTask(TypedDict, total=False):
    id: str
    denial_case_id: str
    department: str
    task_type: str
    description: str
    due_date: str
    status: str
    implemented_by_user_id: Optional[str]
    fix_summary: str
    verified_at: Optional[str]
    monitoring_until_date: Optional[str]
    recurrence_of_task_id: Optional[str]
    reopened_count: int
    created_at: str
    updated_at: str
    version: int


class WriteOffRequest(TypedDict, total=False):
    id: str
    denial_case_id: str
    requested_amount_cents: int
    reason_code: str
    requested_by_user_id: str
    status: str
    approval_tier: str
    projected_recovery_cents: int
    recommended_writeoff_cents: int
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    denial_status_before: Optional[str]
    decision_reason: str
    created_at: str
    updated_at: str
    version: int


class DepartmentScorecard(TypedDict, total=False):
    id: str
    department: str
    period_start_date: str
    period_end_date: str
    status: str
    denial_count: int
    preventable_denial_count: int
    denied_cents: int
    preventable_denied_cents: int
    recovered_cents: int
    written_off_cents: int
    expired_denial_count: int
    auto_writeoff_request_count: int
    verified_fix_count: int
    recurrence_count: int
    verified_linked_denied_cents: int
    recurrence_linked_denied_cents: int
    open_task_count: int
    prevention_score_incidence: Optional[float]
    prevention_score_financial: Optional[float]
    score_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PreventionProgram(TypedDict, total=False):
    id: str
    department: str
    name: str
    start_date: str
    end_date: str
    target_reduction_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DenialEvent(TypedDict, total=False):
    # Append-only audit record: carries ONLY id + created_at (PRD §2.5, §2.11).
    id: str
    denial_case_id: str
    event_type: str
    actor_role: str
    actor_user_id: str
    detail: str
    created_at: str
