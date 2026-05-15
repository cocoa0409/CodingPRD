"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes resources with common_fields (Company, HrUser,
JobPosting, Candidate, Application, InterviewRound, Offer, Onboarding,
HeadhunterContract — carry id/created_at/updated_at/version) from
resources that carry only id + created_at (CommissionRecord,
AuditEvent — append-only / one-way lifecycle).
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    HR_USER = "HrUser"
    HIRING_MANAGER = "HiringManager"
    HR_APPROVER = "HrApprover"
    FINANCE_APPROVER = "FinanceApprover"
    CANDIDATE = "Candidate"
    HEADHUNTER_USER = "HeadhunterUser"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CompanyVerificationStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    BLACKLISTED = "BLACKLISTED"


class CompanyVerificationTier(str, Enum):
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class CompanyIndustry(str, Enum):
    TECH = "TECH"
    FINANCE = "FINANCE"
    MANUFACTURING = "MANUFACTURING"
    RETAIL = "RETAIL"
    HEALTHCARE = "HEALTHCARE"
    EDUCATION = "EDUCATION"
    OTHER = "OTHER"


class CompanySizeBand(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    ENTERPRISE = "ENTERPRISE"


class HrUserBindingStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PostingStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REJECTED = "REJECTED"
    LIVE = "LIVE"
    OFF_SHELF = "OFF_SHELF"
    EXPIRED = "EXPIRED"


class PostingRejectionReason(str, Enum):
    DISCRIMINATORY_WORDING = "DISCRIMINATORY_WORDING"
    ILLEGAL_TERMS = "ILLEGAL_TERMS"
    DUPLICATE = "DUPLICATE"
    OTHER = "OTHER"


class VisibilityMode(str, Enum):
    PUBLIC = "PUBLIC"
    COMPANY_ONLY = "COMPANY_ONLY"
    HIDDEN = "HIDDEN"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    READ = "READ"
    FORWARDED = "FORWARDED"
    INTERVIEW = "INTERVIEW"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class SourceChannel(str, Enum):
    DIRECT = "DIRECT"
    ONE_CLICK = "ONE_CLICK"
    HEADHUNTER = "HEADHUNTER"


class InterviewMode(str, Enum):
    ONSITE = "ONSITE"
    PHONE = "PHONE"
    VIDEO = "VIDEO"


class InterviewRoundStatus(str, Enum):
    DRAFT = "DRAFT"
    AWAITING_CANDIDATE = "AWAITING_CANDIDATE"
    SCHEDULED = "SCHEDULED"
    FEEDBACK_PENDING = "FEEDBACK_PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FeedbackDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    HOLD = "HOLD"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_HM = "PENDING_HM"
    PENDING_HR = "PENDING_HR"
    PENDING_FINANCE = "PENDING_FINANCE"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"


class RescissionReason(str, Enum):
    BUSINESS_NEED = "BUSINESS_NEED"
    BACKGROUND_FAIL = "BACKGROUND_FAIL"
    CANDIDATE_MISREP = "CANDIDATE_MISREP"
    OTHER = "OTHER"


class CheckStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class OnboardingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKS_RUNNING = "CHECKS_RUNNING"
    READY = "READY"
    ONBOARDED = "ONBOARDED"
    NO_SHOW = "NO_SHOW"
    PROBATION_PASSED = "PROBATION_PASSED"
    PROBATION_FAILED = "PROBATION_FAILED"


class CheckKind(str, Enum):
    BACKGROUND = "BACKGROUND"
    MEDICAL = "MEDICAL"


class FeeModel(str, Enum):
    SUCCESS_FEE = "SUCCESS_FEE"
    RETAINER = "RETAINER"
    HYBRID = "HYBRID"


class TriggerEvent(str, Enum):
    OFFER_ACCEPTED = "OFFER_ACCEPTED"
    ONBOARDED = "ONBOARDED"
    PROBATION_PASSED = "PROBATION_PASSED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SettlementStatus(str, Enum):
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"
    CLAWED_BACK = "CLAWED_BACK"


class AuditEventKind(str, Enum):
    STATE_TRANSITION = "STATE_TRANSITION"
    COMMISSION_ACCRUED = "COMMISSION_ACCRUED"
    COMMISSION_SETTLED = "COMMISSION_SETTLED"
    COMMISSION_CLAWBACK = "COMMISSION_CLAWBACK"


class AuditSubjectEntity(str, Enum):
    COMPANY = "Company"
    JOB_POSTING = "JobPosting"
    APPLICATION = "Application"
    INTERVIEW_ROUND = "InterviewRound"
    OFFER = "Offer"
    ONBOARDING = "Onboarding"
    COMMISSION_RECORD = "CommissionRecord"


class ConversionDecision(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FeedbackSide(str, Enum):
    CANDIDATE = "CANDIDATE"
    EMPLOYER = "EMPLOYER"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true (carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Company(TypedDict, total=False):
    id: str
    legal_name: str
    business_license_number: str
    industry: str
    size_band: str
    verification_status: str
    verification_tier: str
    verified_at: Optional[str]
    reverification_due_at: Optional[str]
    authorized_hr_user_ids: List[str]
    active_job_posting_count: int
    posting_quota_limit: int
    blacklist_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HrUser(TypedDict, total=False):
    id: str
    company_id: str
    email: str
    display_name: str
    binding_status: str
    created_at: str
    updated_at: str
    version: int


class JobPosting(TypedDict, total=False):
    id: str
    company_id: str
    title: str
    description: str
    salary_min_cents: int
    salary_max_cents: int
    benefits: List[str]
    posting_status: str
    review_rejection_reason: Optional[str]
    content_fingerprint: Optional[str]
    listed_at: Optional[str]
    off_shelf_at: Optional[str]
    application_count: int
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    resume_attachment_url: str
    visibility_mode: str
    visible_to_company_ids: List[str]
    last_application_at: Optional[str]
    applications_last_60s_count: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    candidate_id: str
    job_posting_id: str
    company_id: str
    application_status: str
    read_at: Optional[str]
    forwarded_at: Optional[str]
    source_channel: str
    headhunter_contract_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InterviewRound(TypedDict, total=False):
    id: str
    application_id: str
    round_index: int
    mode: str
    interviewer_user_ids: List[str]
    candidate_time_slot_options: List[str]
    scheduled_start_at: Optional[str]
    scheduled_end_at: Optional[str]
    round_status: str
    feedback_decision: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    application_id: str
    company_id: str
    base_salary_cents: int
    sign_on_bonus_cents: int
    offer_status: str
    hm_approver_user_id: Optional[str]
    hr_approver_user_id: Optional[str]
    finance_approver_user_id: Optional[str]
    issued_at: Optional[str]
    acceptance_deadline_at: Optional[str]
    accepted_at: Optional[str]
    competing_offer_note: Optional[str]
    rescission_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Onboarding(TypedDict, total=False):
    id: str
    offer_id: str
    start_date: str
    background_check_status: str
    medical_check_status: str
    onboarding_status: str
    probation_end_at: Optional[str]
    candidate_feedback_score: Optional[int]
    employer_feedback_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class HeadhunterContract(TypedDict, total=False):
    id: str
    headhunter_user_id: str
    company_id: str
    fee_model: str
    success_fee_pct_bps: Optional[int]
    retainer_amount_cents: Optional[int]
    trigger_event: str
    clawback_window_days: int
    tax_withholding_pct_bps: int
    contract_status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — common_fields: false (carry id + created_at only)
# ---------------------------------------------------------------------------
class CommissionRecord(TypedDict, total=False):
    id: str
    headhunter_contract_id: str
    application_id: str
    gross_commission_cents: int
    tax_withheld_cents: int
    net_settlement_cents: int
    settlement_status: str
    trigger_kind: str
    settled_at: Optional[str]
    clawback_amount_cents: int
    created_at: str


class AuditEvent(TypedDict, total=False):
    id: str
    subject_entity: str
    subject_id: str
    event_kind: str
    from_state: Optional[str]
    to_state: Optional[str]
    actor_role: str
    actor_user_id: str
    created_at: str


__all__ = [
    "UserRole",
    "CompanyVerificationStatus",
    "CompanyVerificationTier",
    "CompanyIndustry",
    "CompanySizeBand",
    "HrUserBindingStatus",
    "PostingStatus",
    "PostingRejectionReason",
    "VisibilityMode",
    "ApplicationStatus",
    "SourceChannel",
    "InterviewMode",
    "InterviewRoundStatus",
    "FeedbackDecision",
    "OfferStatus",
    "RescissionReason",
    "CheckStatus",
    "OnboardingStatus",
    "CheckKind",
    "FeeModel",
    "TriggerEvent",
    "ContractStatus",
    "SettlementStatus",
    "AuditEventKind",
    "AuditSubjectEntity",
    "ConversionDecision",
    "FeedbackSide",
    "Company",
    "HrUser",
    "JobPosting",
    "Candidate",
    "Application",
    "InterviewRound",
    "Offer",
    "Onboarding",
    "HeadhunterContract",
    "CommissionRecord",
    "AuditEvent",
]
