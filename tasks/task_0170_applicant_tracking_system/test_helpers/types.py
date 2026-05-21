"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 common-fields treatment:

    "Entities with the common-fields treatment — `Recruiter`,
    `HiringManager`, `Interviewer`, `Requisition`, `Candidate`,
    `Application`, `Interview`, `Offer`, `BackgroundCheck`,
    `ReferralBonus`, and `DiversityGoal` — additionally carry
    `created_at` and `updated_at` as ISO 8601 UTC timestamps with three
    fractional digits, and a `version` field which is an integer that
    starts at 1 on creation and increments by one on every mutation."

    "Two entities are deliberately exceptions and do NOT carry
    `updated_at` or `version` — they carry only `id` and `created_at`.
    These are `EEORecord` ... and `OfferApprovalStep` ...
    `InterviewFeedback` likewise carries only `id` and `created_at`
    and is immutable after submission."

Therefore EEORecord, OfferApprovalStep, and InterviewFeedback are
append-only — their TypedDicts omit `updated_at` and `version`.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    RECRUITER = "Recruiter"
    HIRING_MANAGER = "HiringManager"
    INTERVIEWER = "Interviewer"
    CANDIDATE = "Candidate"
    COMPENSATION = "Compensation"
    EXECUTIVE = "Executive"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PAYROLL_OPERATOR = "PayrollOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ===========================================================================
# Enums for entity field values — PRD §3
# ===========================================================================
class SeniorityLevel(str, Enum):
    JUNIOR = "JUNIOR"
    MID = "MID"
    SENIOR = "SENIOR"
    STAFF = "STAFF"
    PRINCIPAL = "PRINCIPAL"


class CandidateSource(str, Enum):
    DIRECT = "DIRECT"
    AGENCY = "AGENCY"
    REFERRAL = "REFERRAL"
    EVENT = "EVENT"
    INBOUND = "INBOUND"


class RequisitionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    OPEN = "OPEN"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ApplicationStage(str, Enum):
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    INTERVIEWING = "INTERVIEWING"
    OFFER_STAGE = "OFFER_STAGE"
    HIRED = "HIRED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class RejectionReason(str, Enum):
    NOT_QUALIFIED = "NOT_QUALIFIED"
    FAILED_INTERVIEW = "FAILED_INTERVIEW"
    FAILED_BACKGROUND_CHECK = "FAILED_BACKGROUND_CHECK"
    OFFER_DECLINED = "OFFER_DECLINED"
    DUPLICATE = "DUPLICATE"
    OTHER = "OTHER"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class InterviewRecommendation(str, Enum):
    STRONG_HIRE = "STRONG_HIRE"
    HIRE = "HIRE"
    NO_HIRE = "NO_HIRE"
    STRONG_NO_HIRE = "STRONG_NO_HIRE"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    NEGOTIATING = "NEGOTIATING"
    APPROVED = "APPROVED"
    EXTENDED = "EXTENDED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    RESCINDED = "RESCINDED"
    EXPIRED = "EXPIRED"


class ApproverRole(str, Enum):
    HIRING_MANAGER = "HIRING_MANAGER"
    COMPENSATION = "COMPENSATION"
    EXECUTIVE = "EXECUTIVE"


class StepDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class BackgroundCheckVendor(str, Enum):
    ACME_BG = "ACME_BG"
    VERIFY_INC = "VERIFY_INC"
    FED_CHECKS = "FED_CHECKS"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BackgroundCheckOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ReferralBonusStatus(str, Enum):
    ACCRUED = "ACCRUED"
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"


class EEOGender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"
    NON_BINARY = "NON_BINARY"
    DECLINE = "DECLINE"


class EEOEthnicity(str, Enum):
    HISPANIC_LATINO = "HISPANIC_LATINO"
    WHITE = "WHITE"
    BLACK_AFRICAN_AMERICAN = "BLACK_AFRICAN_AMERICAN"
    NATIVE_HAWAIIAN_PI = "NATIVE_HAWAIIAN_PI"
    ASIAN = "ASIAN"
    AMERICAN_INDIAN_AN = "AMERICAN_INDIAN_AN"
    TWO_OR_MORE = "TWO_OR_MORE"
    DECLINE = "DECLINE"


class EEOVeteranStatus(str, Enum):
    NOT_VETERAN = "NOT_VETERAN"
    PROTECTED_VETERAN = "PROTECTED_VETERAN"
    OTHER_VETERAN = "OTHER_VETERAN"
    DECLINE = "DECLINE"


class EEODisabilityStatus(str, Enum):
    YES = "YES"
    NO = "NO"
    DECLINE = "DECLINE"


class SystemEventType(str, Enum):
    OFFER_EXPIRY_SWEEP = "OFFER_EXPIRY_SWEEP"
    REFERRAL_PAYABLE_SWEEP = "REFERRAL_PAYABLE_SWEEP"


# ===========================================================================
# Entity TypedDicts — common-fields entities carry id + created_at +
# updated_at + version. Append-only entities (EEORecord,
# InterviewFeedback, OfferApprovalStep) carry only id + created_at.
# ===========================================================================
class Recruiter(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    department_code: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class HiringManager(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    department_code: str
    budget_cents: int
    created_at: str
    updated_at: str
    version: int


class Interviewer(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    department_code: str
    is_certified_for_eeo: bool
    created_at: str
    updated_at: str
    version: int


class Requisition(TypedDict, total=False):
    id: str
    recruiter_id: str
    hiring_manager_id: str
    job_title: str
    department_code: str
    seniority_level: str
    headcount: int
    filled_count: int
    active_offer_count: int
    posted_at: Optional[str]
    closed_at: Optional[str]
    budget_cents: int
    target_diversity_goal_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    source: str
    referrer_employee_id: Optional[str]
    is_in_eeo_protected_class: bool
    created_at: str
    updated_at: str
    version: int


# Append-only — carries only id + created_at + entity-specific fields
class EEORecord(TypedDict, total=False):
    id: str
    candidate_id: str
    gender: str
    ethnicity: str
    veteran_status: str
    disability_status: str
    submitted_at: str
    created_at: str


class Application(TypedDict, total=False):
    id: str
    requisition_id: str
    candidate_id: str
    stage: str
    rejection_reason: Optional[str]
    panel_average_score: Optional[float]
    pinned_eeo_snapshot_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Interview(TypedDict, total=False):
    id: str
    application_id: str
    interviewer_id: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only — carries only id + created_at + entity-specific fields
class InterviewFeedback(TypedDict, total=False):
    id: str
    interview_id: str
    interviewer_id: str
    overall_score: int
    recommendation: str
    submitted_at: str
    created_at: str


class Offer(TypedDict, total=False):
    id: str
    application_id: str
    requisition_id: str
    base_salary_cents: int
    sign_on_bonus_cents: int
    annual_equity_cents: int
    total_first_year_comp_cents: int
    pinned_requisition_version: Optional[int]
    status: str
    expires_at: Optional[str]
    negotiation_round: int
    created_at: str
    updated_at: str
    version: int


# Append-only — carries only id + created_at + entity-specific fields
class OfferApprovalStep(TypedDict, total=False):
    id: str
    offer_id: str
    step_order: int
    approver_role: str
    required_approver_id: str
    decision: str
    decided_at: Optional[str]
    created_at: str


class BackgroundCheck(TypedDict, total=False):
    id: str
    offer_id: str
    vendor: str
    status: str
    ordered_at: str
    result_received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReferralBonus(TypedDict, total=False):
    id: str
    candidate_id: str
    referrer_employee_id: str
    requisition_id: str
    base_amount_cents: int
    diversity_uplift_cents: int
    total_amount_cents: int
    status: str
    payable_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiversityGoal(TypedDict, total=False):
    id: str
    department_code: str
    period_year: int
    target_protected_class_percentage: float
    realized_percentage: float
    projected_percentage: float
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "SeniorityLevel",
    "CandidateSource",
    "RequisitionStatus",
    "ApplicationStage",
    "RejectionReason",
    "InterviewStatus",
    "InterviewRecommendation",
    "OfferStatus",
    "ApproverRole",
    "StepDecision",
    "BackgroundCheckVendor",
    "BackgroundCheckStatus",
    "BackgroundCheckOutcome",
    "ReferralBonusStatus",
    "EEOGender",
    "EEOEthnicity",
    "EEOVeteranStatus",
    "EEODisabilityStatus",
    "SystemEventType",
    "Recruiter",
    "HiringManager",
    "Interviewer",
    "Requisition",
    "Candidate",
    "EEORecord",
    "Application",
    "Interview",
    "InterviewFeedback",
    "Offer",
    "OfferApprovalStep",
    "BackgroundCheck",
    "ReferralBonus",
    "DiversityGoal",
]
