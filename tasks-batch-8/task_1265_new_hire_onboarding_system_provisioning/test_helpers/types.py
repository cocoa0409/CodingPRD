"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class RoleProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class NewHireStatus(str, Enum):
    REGISTERED = "REGISTERED"
    EMPLOYED = "EMPLOYED"
    RESCINDED = "RESCINDED"
    SEPARATED = "SEPARATED"


class CasePhase(str, Enum):
    PRE_BOARDING = "PRE_BOARDING"
    CLEARANCE_IN_PROGRESS = "CLEARANCE_IN_PROGRESS"
    PROVISIONING = "PROVISIONING"
    DAY_ONE_READY = "DAY_ONE_READY"
    IN_PROGRESS = "IN_PROGRESS"
    PROBATION = "PROBATION"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    REVOKED = "REVOKED"
    SEPARATED = "SEPARATED"


class CaseHealth(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"


class TaskKind(str, Enum):
    DOCUMENT_UPLOAD = "DOCUMENT_UPLOAD"
    FORM_ACK = "FORM_ACK"
    POLICY_READ = "POLICY_READ"


class TaskStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WAIVED = "WAIVED"
    CANCELLED = "CANCELLED"


class ClearanceStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    ESCALATED = "ESCALATED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class ComponentStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    ATTENTION_REQUIRED = "ATTENTION_REQUIRED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ItemKind(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    ACCESS = "ACCESS"


class ItemStatus(str, Enum):
    PENDING = "PENDING"
    IN_FULFILLMENT = "IN_FULFILLMENT"
    DONE = "DONE"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FULL = "FULL"
    CONDUCTED = "CONDUCTED"
    CANCELLED = "CANCELLED"


class OrientationRsvp(str, Enum):
    NONE = "NONE"
    BOOKED = "BOOKED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    SESSION_CANCELLED = "SESSION_CANCELLED"


class CheckInKind(str, Enum):
    MANAGER = "MANAGER"
    BUDDY = "BUDDY"


class CheckInStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class TrainingStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class CycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EVALUATION_DUE = "EVALUATION_DUE"
    EVALUATED_PASS = "EVALUATED_PASS"
    EVALUATED_EXTEND = "EVALUATED_EXTEND"
    EVALUATED_FAIL = "EVALUATED_FAIL"
    CANCELLED = "CANCELLED"


class HandoffStatus(str, Enum):
    DRAFT = "DRAFT"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED_BY_PAYROLL = "REJECTED_BY_PAYROLL"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class SurveyStatus(str, Enum):
    SENT = "SENT"
    SUBMITTED = "SUBMITTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class BenefitsTier(str, Enum):
    STANDARD = "STANDARD"
    PLUS = "PLUS"
    PREMIUM = "PREMIUM"


class UserRole(str, Enum):
    HR_ADMIN = "HRAdmin"
    HIRING_MANAGER = "HiringManager"
    BUDDY = "Buddy"
    NEW_HIRE = "NewHire"
    IT_PROVISIONER = "ITProvisioner"
    BACKGROUND_ADJUDICATOR = "BackgroundAdjudicator"
    PAYROLL_OPS = "PayrollOps"


# Entity TypedDicts (common_fields: true -> id + created_at + updated_at + version)


class RoleProfile(TypedDict, total=False):
    id: str
    name: str
    status: str
    published_version: int
    preboarding_tasks: list
    training_modules: list
    equipment_items: list
    access_grants: list
    probation_days: int
    max_probation_extensions: int
    extension_days: int
    buddy_checkin_interval_days: int
    buddy_checkin_count: int
    manager_checkin_offsets_days: list
    provisioning_sla_hours: int
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    employment_status: str
    manager_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class NewHire(TypedDict, total=False):
    id: str
    full_name: str
    personal_email: str
    start_date: str
    department: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OnboardingCase(TypedDict, total=False):
    id: str
    new_hire_id: str
    role_profile_id: str
    pinned_profile_version: int
    manager_id: str
    buddy_id: str
    start_date: str
    base_salary_cents: int
    signing_bonus_cents: int
    relocation_stipend_cents: int
    benefits_tier: str
    phase: str
    health: str
    health_score: int
    orientation_session_id: Optional[str]
    orientation_rsvp: str
    manager_reassignment_required: bool
    created_at: str
    updated_at: str
    version: int


class OnboardingTask(TypedDict, total=False):
    id: str
    case_id: str
    task_kind: str
    title: str
    is_required: bool
    status: str
    document_ref: Optional[str]
    note: Optional[str]
    review_note: Optional[str]
    reject_count: int
    due_at: str
    sort_index: int
    created_at: str
    updated_at: str
    version: int


class ClearanceCase(TypedDict, total=False):
    id: str
    case_id: str
    status: str
    background_status: str
    reference_status: str
    initiated_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    adjudication_rationale: Optional[str]
    override_clear: bool
    created_at: str
    updated_at: str
    version: int


class ProvisioningOrder(TypedDict, total=False):
    id: str
    case_id: str
    status: str
    pinned_profile_version: int
    sla_hours: int
    submitted_at: Optional[str]
    fulfilled_at: Optional[str]
    elapsed_calendar_hours: float
    elapsed_business_hours: float
    sla_breached_calendar: bool
    sla_breached_business: bool
    created_at: str
    updated_at: str
    version: int


class ProvisioningItem(TypedDict, total=False):
    id: str
    order_id: str
    item_kind: str
    item_name: str
    quantity: int
    status: str
    blocked_reason: Optional[str]
    sort_index: int
    created_at: str
    updated_at: str
    version: int


class OrientationSession(TypedDict, total=False):
    id: str
    room: str
    starts_at: str
    ends_at: str
    capacity: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CheckIn(TypedDict, total=False):
    id: str
    case_id: str
    owner_employee_id: str
    kind: str
    scheduled_at: str
    status: str
    productivity_rating: Optional[int]
    notes: Optional[str]
    completed_at: Optional[str]
    sort_index: int
    created_at: str
    updated_at: str
    version: int


class TrainingAssignment(TypedDict, total=False):
    id: str
    case_id: str
    module_code: str
    due_at: str
    status: str
    score: Optional[float]
    completed_at: Optional[str]
    completed_late: bool
    sort_index: int
    created_at: str
    updated_at: str
    version: int


class ProbationCycle(TypedDict, total=False):
    id: str
    case_id: str
    cycle_index: int
    evaluation_due_at: str
    status: str
    outcome_rating: Optional[int]
    notes: Optional[str]
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollHandoff(TypedDict, total=False):
    id: str
    case_id: str
    status: str
    base_salary_cents: int
    signing_bonus_cents: int
    relocation_stipend_cents: int
    benefits_tier: str
    start_date: str
    first_period_start_date: str
    first_period_end_date: str
    first_period_gross_cents: int
    transmitted_at: Optional[str]
    acknowledged_at: Optional[str]
    benefits_window_end: str
    benefits_window_breached: bool
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict, total=False):
    id: str
    case_id: str
    status: str
    sent_at: str
    expires_at: str
    onboarding_experience_rating: Optional[int]
    manager_support_rating: Optional[int]
    resources_rating: Optional[int]
    overall_score: Optional[float]
    created_at: str
    updated_at: str
    version: int
