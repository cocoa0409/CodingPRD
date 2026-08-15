"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class JobLevel(str, Enum):
    IC = "IC"
    SENIOR = "SENIOR"
    MANAGER = "MANAGER"
    DIRECTOR = "DIRECTOR"
    EXECUTIVE = "EXECUTIVE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TALENT_ADMIN = "TalentAdmin"
    RECRUITER = "Recruiter"
    HIRING_MANAGER = "HiringManager"
    EMPLOYEE = "Employee"
    PAYROLL_PROCESSOR = "PayrollProcessor"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CandidateGlobalStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_PROCESS = "IN_PROCESS"
    HIRED = "HIRED"
    DEPARTED = "DEPARTED"


class RequisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PAUSED = "PAUSED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXHAUSTED = "EXHAUSTED"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    QUALIFIED = "QUALIFIED"
    SCREENING = "SCREENING"
    INTERVIEWING = "INTERVIEWING"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    HIRED = "HIRED"
    COMPLETED = "COMPLETED"
    REJECTED_DUPLICATE = "REJECTED_DUPLICATE"
    REJECTED_PRIOR_CANDIDATE = "REJECTED_PRIOR_CANDIDATE"
    REJECTED_OTHER = "REJECTED_OTHER"
    NOT_SELECTED = "NOT_SELECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    FORFEITED = "FORFEITED"
    RETENTION_FAILED = "RETENTION_FAILED"


class MilestoneKind(str, Enum):
    HIRE = "HIRE"
    RETENTION = "RETENTION"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    EARNED = "EARNED"
    APPROVED = "APPROVED"
    BATCHED = "BATCHED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"
    CLAWED_BACK = "CLAWED_BACK"


class RecoveryStatus(str, Enum):
    PENDING = "PENDING"
    RECOVERED = "RECOVERED"


class BatchStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    EXPORTED = "EXPORTED"
    CONFIRMED_PAID = "CONFIRMED_PAID"
    CANCELLED = "CANCELLED"


class AbuseCaseType(str, Enum):
    SELF_REFERRAL = "SELF_REFERRAL"
    VELOCITY = "VELOCITY"
    DUPLICATE_RING = "DUPLICATE_RING"
    RESUME_FARM = "RESUME_FARM"
    MANUAL = "MANUAL"


class AbuseCaseStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    DISMISSED = "DISMISSED"


class FilingStatus(str, Enum):
    SINGLE = "SINGLE"
    MARRIED = "MARRIED"
    HEAD_OF_HOUSEHOLD = "HEAD_OF_HOUSEHOLD"


class WithholdingMethod(str, Enum):
    FLAT = "FLAT"
    AGGREGATE = "AGGREGATE"


class TaxProfileStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"


# common_fields: true — carries id + created_at + updated_at + version
class Employee(TypedDict, total=False):
    id: str
    employee_number: str
    full_name: str
    email: str
    department: str
    job_level: str
    is_recruiter: bool
    hire_date: str
    employment_status: str
    terminated_at: Optional[str]
    tenure_days: int
    fraud_strikes: int
    risk_score: float
    referral_suspended: bool
    annual_provisional_cents: int
    annual_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    normalized_email: str
    phone: Optional[str]
    prior_application_at: Optional[str]
    global_status: str
    last_terminal_outcome_at: Optional[str]
    cooldown_until: Optional[str]
    hired_via_referral_id: Optional[str]
    departed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class JobRequisition(TypedDict, total=False):
    id: str
    req_number: str
    title: str
    department: str
    level: str
    referral_eligible: bool
    hard_to_fill: bool
    openings: int
    filled_count: int
    status: str
    opened_at: Optional[str]
    filled_by_candidate_id: Optional[str]
    open_referral_count: int
    created_at: str
    updated_at: str
    version: int


class PolicyVersion(TypedDict, total=False):
    id: str
    effective_from: str
    effective_to: Optional[str]
    min_tenure_days: int
    duplicate_cooldown_months: int
    referral_expiry_days: int
    hire_pct: int
    retention_days: int
    clawback_days: int
    annual_cap_cents: int
    velocity_limit: int
    tier_ic_cents: int
    tier_senior_cents: int
    tier_manager_cents: int
    tier_director_cents: int
    tier_executive_cents: int
    status: str
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    name: str
    job_requisition_id: str
    multiplier_bps: int
    flat_addon_cents: int
    window_start: str
    window_end: str
    budget_cents: int
    max_payouts: Optional[int]
    reserved_cents: int
    spent_cents: int
    remaining_cents: int
    payouts_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    referrer_id: str
    candidate_id: str
    job_requisition_id: str
    campaign_id: Optional[str]
    policy_version_id: str
    status: str
    submitted_at: str
    note: Optional[str]
    bonus_base_cents: int
    campaign_uplift_cents: int
    bonus_total_cents: int
    hire_date: Optional[str]
    retention_due_at: Optional[str]
    clawback_until: Optional[str]
    last_decision_reason: Optional[str]
    uplift_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class BonusMilestone(TypedDict, total=False):
    id: str
    referral_id: str
    kind: str
    amount_cents: int
    withholding_cents: Optional[int]
    net_cents: Optional[int]
    status: str
    earned_at: Optional[str]
    payroll_batch_id: Optional[str]
    recovery_status: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayrollBatch(TypedDict, total=False):
    id: str
    period_label: str
    status: str
    total_gross_cents: int
    total_withholding_cents: int
    total_net_cents: int
    milestone_count: int
    created_at: str
    updated_at: str
    version: int


class AbuseCase(TypedDict, total=False):
    id: str
    employee_id: str
    referral_id: Optional[str]
    case_type: str
    risk_weight: int
    status: str
    raised_by_user_id: str
    decided_by_user_id: Optional[str]
    confirmed_at: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaxProfile(TypedDict, total=False):
    id: str
    employee_id: str
    filing_status: str
    withholding_method: str
    supplemental_rate_bps: Optional[int]
    ytd_carryover_cents: int
    ytd_paid_gross_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class ReferralEvent(TypedDict, total=False):
    id: str
    referral_id: str
    event_type: str
    from_state: Optional[str]
    to_state: str
    actor_user_id: str
    note: Optional[str]
    created_at: str
