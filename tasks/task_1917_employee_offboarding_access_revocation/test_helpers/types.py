"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class OffboardingCaseStatus(str, Enum):
    INTAKE = "INTAKE"
    APPROVED = "APPROVED"
    REVOCATION_IN_PROGRESS = "REVOCATION_IN_PROGRESS"
    PAYROLL_PENDING = "PAYROLL_PENDING"
    CLEARANCE_IN_PROGRESS = "CLEARANCE_IN_PROGRESS"
    READY_TO_CLOSE = "READY_TO_CLOSE"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class RevocationPosture(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETE = "COMPLETE"


class AssetPosture(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    DEFAULTED = "DEFAULTED"


class RevocationTaskStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    VERIFIED = "VERIFIED"
    WAIVED = "WAIVED"


class AssetReturnItemStatus(str, Enum):
    TRACKED = "TRACKED"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"
    DEFAULTED = "DEFAULTED"
    WAIVED = "WAIVED"


class DeductionStatus(str, Enum):
    NONE = "NONE"
    COMPUTED = "COMPUTED"
    APPLIED = "APPLIED"
    WAIVED = "WAIVED"


class FinalPayStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    DISBURSED = "DISBURSED"
    LATE = "LATE"
    VOIDED = "VOIDED"


class StateLawVariant(str, Enum):
    IMMEDIATE_ON_TERMINATION = "IMMEDIATE_ON_TERMINATION"
    NEXT_PAYDAY = "NEXT_PAYDAY"
    WITHIN_FIXED_DAYS = "WITHIN_FIXED_DAYS"


class ExitInterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class KTPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    INCOMPLETE_AT_CLOSE = "INCOMPLETE_AT_CLOSE"
    WAIVED = "WAIVED"


class KTSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class BenefitsNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    FAILED = "FAILED"
    ESCALATED = "ESCALATED"


class CovenantAckStatus(str, Enum):
    PENDING = "PENDING"
    REMINDED = "REMINDED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    EXPIRED = "EXPIRED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RehireReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    RETURNED = "RETURNED"


class RehireCode(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    ELIGIBLE_WITH_CONDITIONS = "ELIGIBLE_WITH_CONDITIONS"
    INELIGIBLE = "INELIGIBLE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    HR_PARTNER = "HRPartner"
    HR_REVIEWER = "HRReviewer"
    HR_DIRECTOR = "HRDirector"
    PAYROLL_SPECIALIST = "PayrollSpecialist"
    IT_OPERATOR = "ITOperator"
    IT_VERIFIER = "ITVerifier"
    IT_MANAGER = "ITManager"
    MANAGER = "Manager"
    ASSET_CLERK = "AssetClerk"
    BENEFITS_ADMINISTRATOR = "BenefitsAdministrator"


# common_fields: true — id + created_at + updated_at + version
class OffboardingCase(TypedDict, total=False):
    id: str
    employee_ref: str
    case_type: str
    work_state_code: str
    notice_received_date: str
    requested_last_day: str
    determined_last_day: Optional[str]
    final_pay_due_at: Optional[str]
    pto_balance_hours: float
    tenure_years: float
    hourly_wage_cents: int
    status: str
    revocation_posture: str
    asset_posture: str
    deduction_total_cents: int
    rehire_code: Optional[str]
    closed_at: Optional[str]
    intake_hr_ref: str
    created_at: str
    updated_at: str
    version: int


class AccessRevocationTask(TypedDict, total=False):
    id: str
    offboarding_case_id: str
    system_name: str
    sequence_rank: int
    status: str
    scheduled_at: Optional[str]
    executed_at: Optional[str]
    verified_by: Optional[str]
    retry_count: int
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; carries ONLY id + created_at (no updated_at, no version)
class ManagerNotification(TypedDict, total=False):
    id: str
    offboarding_case_id: str
    notification_kind: str
    sent_at: str
    recipient_manager_ref: str
    suppressed: bool
    created_at: str


class AssetReturnItem(TypedDict, total=False):
    id: str
    offboarding_case_id: str
    asset_tag: str
    asset_kind: str
    replacement_cost_cents: int
    issued_date: str
    return_due_at: Optional[str]
    returned_at: Optional[str]
    condition_on_return: Optional[str]
    status: str
    deduction_status: str
    deduction_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class FinalPayStatement(TypedDict, total=False):
    id: str
    offboarding_case_id: str
    regular_wages_cents: int
    pto_payout_cents: int
    deduction_total_cents: int
    net_pay_cents: int
    state_law_variant: str
    due_at: str
    status: str
    disbursed_at: Optional[str]
    late_penalty_cents: int
    calc_by_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExitInterview(TypedDict, total=False):
    id: str
    offboarding_case_id: str
    interviewer_ref: str
    scheduled_start: str
    scheduled_end: str
    status: str
    reschedule_count: int
    completion_notes_ref: Optional[str]
    declined_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KnowledgeTransferPlan(TypedDict, total=False):
    id: str
    offboarding_case_id: str
    owner_manager_ref: Optional[str]
    required_session_count: int
    status: str
    completed_session_count: int
    waived_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KnowledgeTransferSession(TypedDict, total=False):
    id: str
    knowledge_transfer_plan_id: str
    topic: str
    scheduled_start: str
    scheduled_end: str
    successor_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitsNotice(TypedDict, total=False):
    id: str
    offboarding_case_id: str
    notice_kind: str
    status: str
    send_by: Optional[str]
    sent_at: Optional[str]
    acknowledged_at: Optional[str]
    failure_count: int
    created_at: str
    updated_at: str
    version: int


class RestrictiveCovenantAck(TypedDict, total=False):
    id: str
    offboarding_case_id: str
    covenant_kind: str
    status: str
    remind_at: Optional[str]
    acknowledged_at: Optional[str]
    acknowledgment_text_version: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RehireEligibilityReview(TypedDict, total=False):
    id: str
    offboarding_case_id: str
    reviewer_hr_ref: str
    recommended_code: str
    status: str
    finalized_at: Optional[str]
    rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int
