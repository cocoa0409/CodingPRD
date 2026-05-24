"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this PRD carry id + created_at + updated_at + version
(PRD §2.4: "All nine of these entities additionally expose an updated_at
timestamp and an integer version field").
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Status enums (per §3 lifecycle descriptions) -----------------------

class ApplicantProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"


class RecommenderInviteStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class SchoolPosture(str, Enum):
    OPEN = "OPEN"
    AT_TARGET = "AT_TARGET"
    OVER_TARGET = "OVER_TARGET"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADMITTED = "ADMITTED"
    WAITLISTED = "WAITLISTED"
    DENIED = "DENIED"
    DEFERRED = "DEFERRED"
    WITHDRAWN = "WITHDRAWN"
    ENROLLED = "ENROLLED"
    DECLINED_OFFER = "DECLINED_OFFER"


class ApplicationPlan(str, Enum):
    EARLY_DECISION = "EARLY_DECISION"
    EARLY_ACTION = "EARLY_ACTION"
    REGULAR = "REGULAR"
    ROLLING = "ROLLING"


class RecommendationLetterStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_PROGRESS = "IN_PROGRESS"
    SUBMITTED = "SUBMITTED"
    WAIVED = "WAIVED"


class FinancialAidProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"


class AidOfferVariant(str, Enum):
    FEDERAL = "FEDERAL"
    INSTITUTIONAL = "INSTITUTIONAL"


class RecommenderRelationship(str, Enum):
    TEACHER = "TEACHER"
    COUNSELOR = "COUNSELOR"
    OTHER = "OTHER"


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    RECOMMENDER = "Recommender"
    ADMISSIONS_OFFICER = "AdmissionsOfficer"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class DecisionType(str, Enum):
    ADMIT = "ADMIT"
    WAITLIST = "WAITLIST"
    DENY = "DENY"
    DEFER = "DEFER"


# --- Entity TypedDicts ---------------------------------------------------

class Applicant(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    gpa: float
    sat_total: Optional[int]
    profile_status: str
    created_at: str
    updated_at: str
    version: int


class Recommender(TypedDict, total=False):
    id: str
    applicant_id: str
    email: str
    full_name: str
    relationship: str
    invite_status: str
    created_at: str
    updated_at: str
    version: int


class School(TypedDict, total=False):
    id: str
    name: str
    target_class_size: int
    ed_deadline_iso: str
    ea_deadline_iso: str
    rd_deadline_iso: str
    rolling_open: bool
    requires_css_profile: bool
    confirmed_enrollment_count: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    school_id: str
    plan: str
    status: str
    submitted_at: Optional[str]
    decision_at: Optional[str]
    waitlist_rank: Optional[int]
    waitlist_added_at: Optional[str]
    admission_probability_score: int
    created_at: str
    updated_at: str
    version: int


class EssaySubmission(TypedDict, total=False):
    id: str
    application_id: str
    prompt_code: str
    body: str
    word_count: int
    locked: bool
    created_at: str
    updated_at: str
    version: int


class RecommendationLetter(TypedDict, total=False):
    id: str
    application_id: str
    recommender_id: str
    status: str
    body: Optional[str]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancialAidProfile(TypedDict, total=False):
    id: str
    applicant_id: str
    fafsa_efc_cents: int
    css_efc_cents: Optional[int]
    family_income_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AidOffer(TypedDict, total=False):
    id: str
    application_id: str
    cost_of_attendance_cents: int
    variant: str
    demonstrated_need_cents: int
    grant_cents: int
    loan_cents: int
    work_study_cents: int
    net_price_cents: int
    created_at: str
    updated_at: str
    version: int


class AdmissionCycle(TypedDict, total=False):
    id: str
    school_id: str
    clock_iso: str
    last_yield_run_at: Optional[str]
    yield_run_count: int
    cooldown_ms: int
    created_at: str
    updated_at: str
    version: int
