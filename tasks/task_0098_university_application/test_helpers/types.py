"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD §2.4: Applicant, University, Program, Application,
RecommendationRequest, FinancialAidPackage, WaitlistEntry carry
id/created_at/updated_at/version. EssaySubmission and YieldSweep
are exceptions — they carry only id and created_at; no updated_at
and no version.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    APPLICANT = "Applicant"
    RECOMMENDER = "Recommender"
    ADMISSIONS_OFFICER = "AdmissionsOfficer"
    FINANCIAL_AID_OFFICER = "FinancialAidOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Application (PRD §3.3, §3.6, §3.7, §3.10)
# ---------------------------------------------------------------------------
class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"
    WAITLISTED = "WAITLISTED"
    ENROLLED = "ENROLLED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationRound(str, Enum):
    EARLY_DECISION = "EARLY_DECISION"
    REGULAR_DECISION = "REGULAR_DECISION"
    ROLLING = "ROLLING"


class AdmissionDecision(str, Enum):
    ADMIT = "ADMIT"
    REJECT = "REJECT"
    WAITLIST = "WAITLIST"


# ---------------------------------------------------------------------------
# RecommendationRequest (PRD §3.5)
# ---------------------------------------------------------------------------
class RecommendationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    SUBMITTED = "SUBMITTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# FinancialAidPackage (PRD §3.8)
# ---------------------------------------------------------------------------
class FinancialAidStatus(str, Enum):
    REQUESTED = "REQUESTED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REVOKED = "REVOKED"


class AidMethod(str, Enum):
    FEDERAL_METHODOLOGY = "FEDERAL_METHODOLOGY"
    INSTITUTIONAL_METHODOLOGY = "INSTITUTIONAL_METHODOLOGY"


# ---------------------------------------------------------------------------
# WaitlistEntry (PRD §3.9)
# ---------------------------------------------------------------------------
class WaitlistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    RELEASED = "RELEASED"


# ===========================================================================
# Entity TypedDicts
# ===========================================================================

# Common-fields entities — PRD §2.4: id, created_at, updated_at, version.
class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    date_of_birth: str
    high_school_gpa: float
    household_income_cents: int
    fafsa_efc_cents: Optional[int]
    css_profile_efc_cents: Optional[int]
    ed_commitment_application_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class University(TypedDict, total=False):
    id: str
    name: str
    yield_target_count: int
    regular_decision_deadline: str
    early_decision_deadline: str
    rolling_admission_enabled: bool
    enrolled_count: int
    created_at: str
    updated_at: str
    version: int


class Program(TypedDict, total=False):
    id: str
    university_id: str
    name: str
    capacity: int
    admitted_count: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    program_id: str
    round: str
    status: str
    essay_id: Optional[str]
    required_recommendation_count: int
    submitted_at: Optional[str]
    admission_decision_at: Optional[str]
    enrollment_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecommendationRequest(TypedDict, total=False):
    id: str
    application_id: str
    recommender_email: str
    status: str
    invitation_expires_at: str
    letter_body: Optional[str]
    letter_word_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FinancialAidPackage(TypedDict, total=False):
    id: str
    application_id: str
    aid_method: str
    status: str
    cost_of_attendance_cents: int
    grant_cents: int
    loan_cents: int
    work_study_cents: int
    total_award_cents: int
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict, total=False):
    id: str
    application_id: str
    program_id: str
    status: str
    rank_score: float
    offered_at: Optional[str]
    offer_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only entities — PRD §2.4: only id and created_at;
# NO updated_at and NO version.
class EssaySubmission(TypedDict, total=False):
    id: str
    application_id: str
    prompt_code: str
    body: str
    word_count: int
    customization_score: float
    created_at: str


class YieldSweep(TypedDict, total=False):
    id: str
    university_id: str
    epoch: int
    enrolled_count_at_start: int
    offers_extended: int
    ran_at: str
    created_at: str


__all__ = [
    "UserRole",
    "ApplicationStatus",
    "ApplicationRound",
    "AdmissionDecision",
    "RecommendationStatus",
    "FinancialAidStatus",
    "AidMethod",
    "WaitlistStatus",
    "Applicant",
    "University",
    "Program",
    "Application",
    "RecommendationRequest",
    "FinancialAidPackage",
    "WaitlistEntry",
    "EssaySubmission",
    "YieldSweep",
]
