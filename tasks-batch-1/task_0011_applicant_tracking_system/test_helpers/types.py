"""Domain types: entity TypedDicts, status enums, role enum (PRD §1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------- Status enums ----------------

class JobRequisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ApplicationStatus(str, Enum):
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    INTERVIEWING = "INTERVIEWING"
    OFFER_EXTENDED = "OFFER_EXTENDED"
    HIRED = "HIRED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OfferStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXTENDED = "EXTENDED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"


class BackgroundCheckStatus(str, Enum):
    INITIATED = "INITIATED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class ReferralBonusStatus(str, Enum):
    PENDING_BGC = "PENDING_BGC"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    VOID = "VOID"


class InterviewRecommendation(str, Enum):
    STRONG_HIRE = "STRONG_HIRE"
    HIRE = "HIRE"
    NO_HIRE = "NO_HIRE"
    STRONG_NO_HIRE = "STRONG_NO_HIRE"


class TargetLevel(str, Enum):
    JUNIOR = "JUNIOR"
    MID = "MID"
    SENIOR = "SENIOR"
    STAFF = "STAFF"


class SourceChannel(str, Enum):
    DIRECT = "DIRECT"
    REFERRAL = "REFERRAL"
    AGENCY = "AGENCY"
    JOB_BOARD = "JOB_BOARD"


class EeoEthnicity(str, Enum):
    WHITE = "WHITE"
    BLACK = "BLACK"
    HISPANIC = "HISPANIC"
    ASIAN = "ASIAN"
    NATIVE = "NATIVE"
    PACIFIC = "PACIFIC"
    TWO_OR_MORE = "TWO_OR_MORE"
    DECLINED = "DECLINED"


class EeoGender(str, Enum):
    FEMALE = "FEMALE"
    MALE = "MALE"
    NONBINARY = "NONBINARY"
    DECLINED = "DECLINED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RECRUITER = "Recruiter"
    HIRING_MANAGER = "HiringManager"
    COMP_APPROVER = "CompApprover"
    VP = "VP"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PAYROLL_OFFICER = "PayrollOfficer"
    CANDIDATE = "Candidate"


# ---------------- Entity TypedDicts ----------------

# common_fields: true — id + created_at + updated_at + version
class Department(TypedDict, total=False):
    id: str
    name: str
    cost_center_code: str
    hiring_budget_cents: int
    committed_offer_cents: int
    created_at: str
    updated_at: str
    version: int


class JobRequisition(TypedDict, total=False):
    id: str
    department_id: str
    title: str
    target_level: str
    base_salary_min_cents: int
    base_salary_max_cents: int
    openings: int
    filled_count: int
    status: str
    submitter_user_id: Optional[str]
    approver_user_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    source_channel: str
    referrer_user_id: Optional[str]
    eeo_ethnicity: str
    eeo_gender: str
    eeo_veteran: bool
    eeo_disability: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    candidate_id: str
    requisition_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict, total=False):
    id: str
    application_id: str
    round_number: int
    scheduled_at: str
    duration_minutes: int
    panel_user_ids: List[str]
    status: str
    aggregate_score: Optional[float]
    recommendation: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, ONLY id + created_at
class InterviewFeedback(TypedDict, total=False):
    id: str
    interview_id: str
    panelist_user_id: str
    score: int
    comments: str
    created_at: str


class Offer(TypedDict, total=False):
    id: str
    application_id: str
    base_salary_cents: int
    signing_bonus_cents: int
    status: str
    submitter_user_id: Optional[str]
    comp_approver_user_id: Optional[str]
    vp_approver_user_id: Optional[str]
    extended_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackgroundCheck(TypedDict, total=False):
    id: str
    offer_id: str
    candidate_id: str
    status: str
    vendor_reference: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReferralBonus(TypedDict, total=False):
    id: str
    candidate_id: str
    referrer_user_id: str
    offer_id: str
    estimated_amount_cents: int
    payable_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class DiversityGoal(TypedDict, total=False):
    id: str
    department_id: str
    target_level: str
    period_year: int
    target_underrepresented_pct: float
    pool_underrepresented_pct: float
    hire_underrepresented_pct: float
    created_at: str
    updated_at: str
    version: int
