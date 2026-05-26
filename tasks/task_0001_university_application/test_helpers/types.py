"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ──────────────────────────────────────────────────────────

class ApplicantProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADMITTED = "ADMITTED"
    WAITLISTED = "WAITLISTED"
    DENIED = "DENIED"
    ENROLLED = "ENROLLED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class AdmissionTrack(str, Enum):
    EARLY_DECISION = "EARLY_DECISION"
    EARLY_ACTION = "EARLY_ACTION"
    REGULAR = "REGULAR"
    ROLLING = "ROLLING"


class Residency(str, Enum):
    IN_STATE = "IN_STATE"
    OUT_OF_STATE = "OUT_OF_STATE"
    INTERNATIONAL = "INTERNATIONAL"


class YieldPosture(str, Enum):
    OPEN = "OPEN"
    ON_TARGET = "ON_TARGET"
    OVER_TARGET = "OVER_TARGET"


class RecommendationStatus(str, Enum):
    INVITED = "INVITED"
    SUBMITTED = "SUBMITTED"
    WAIVED = "WAIVED"


class AidPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    REVOKED = "REVOKED"


class WaitlistEntryStatus(str, Enum):
    PENDING = "PENDING"
    PROMOTED = "PROMOTED"
    RELEASED = "RELEASED"


class ProfileType(str, Enum):
    FAFSA = "FAFSA"
    CSS_PROFILE = "CSS_PROFILE"


class UserRole(str, Enum):
    APPLICANT = "Applicant"
    ADMISSIONS_OFFICER = "AdmissionsOfficer"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ──

class Applicant(TypedDict):
    id: str
    email: str
    full_name: str
    gpa_unweighted: float
    sat_total: Optional[int]
    residency: str
    profile_status: str
    submitted_application_count: int
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    name: str
    state_code: str
    admission_track: str
    deadline_iso: str
    decision_release_iso: str
    target_class_size: int
    assumed_yield_rate: float
    in_state_tuition_cents: int
    out_of_state_tuition_cents: int
    international_tuition_cents: int
    admitted_count: int
    enrolled_count: int
    declined_count: int
    denied_count: int
    yield_posture: str
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    applicant_id: str
    school_id: str
    status: str
    admission_track_snapshot: Optional[str]
    submitted_at: Optional[str]
    decision_at: Optional[str]
    enrollment_decision_at: Optional[str]
    composite_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Essay(TypedDict):
    id: str
    application_id: str
    prompt_code: str
    word_count: int
    text: str
    completed: bool
    created_at: str
    updated_at: str
    version: int


class RecommendationRequest(TypedDict):
    id: str
    applicant_id: str
    school_id: str
    recommender_email: str
    status: str
    submitted_at: Optional[str]
    rating: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FinancialAidProfile(TypedDict):
    id: str
    applicant_id: str
    profile_type: str
    household_income_cents: int
    household_size: int
    declared_assets_cents: int
    expected_family_contribution_cents: int
    created_at: str
    updated_at: str
    version: int


class AidPackage(TypedDict):
    id: str
    application_id: str
    status: str
    grant_cents: int
    loan_cents: int
    work_study_cents: int
    net_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    application_id: str
    rank: int
    status: str
    promoted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — SystemClock omits updated_at/version (PRD §2.4)
class SystemClock(TypedDict):
    id: str
    current_utc: str
    created_at: str
