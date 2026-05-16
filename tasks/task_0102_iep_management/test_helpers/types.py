"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 distinguishes two common-fields shapes:

- Entities carrying id + created_at + updated_at + version: District,
  Student, EligibilityEvaluation, IEP, IEPGoal, RelatedService,
  ServiceSession, TransitionPlan.
- Append-only event records carrying ONLY id + created_at:
  ParentalConsent and GoalProgressReport. PRD §2.4: "Two entity types
  are append-only event records and therefore do not carry updated_at
  or version: ParentalConsent ... and GoalProgressReport".
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DISTRICT_ADMIN = "DistrictAdmin"
    SCHOOL_PSYCHOLOGIST = "SchoolPsychologist"
    SPECIAL_EDUCATION_TEACHER = "SpecialEducationTeacher"
    RELATED_SERVICE_PROVIDER = "RelatedServiceProvider"
    PARENT = "Parent"


# ---------------------------------------------------------------------------
# Status enums — PRD §3 state machines
# ---------------------------------------------------------------------------
class EvaluationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONSENT_PENDING = "CONSENT_PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class EvaluationType(str, Enum):
    INITIAL = "INITIAL"
    TRIENNIAL = "TRIENNIAL"
    INTERIM = "INTERIM"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class ConsentScope(str, Enum):
    EVALUATION = "EVALUATION"
    IEP_IMPLEMENTATION = "IEP_IMPLEMENTATION"
    RELATED_SERVICE = "RELATED_SERVICE"
    PLACEMENT_CHANGE = "PLACEMENT_CHANGE"


class IepStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class IepGoalStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    MET = "MET"
    NOT_MET = "NOT_MET"
    DISCONTINUED = "DISCONTINUED"


class GoalDomain(str, Enum):
    ACADEMIC = "ACADEMIC"
    COMMUNICATION = "COMMUNICATION"
    MOTOR = "MOTOR"
    BEHAVIORAL = "BEHAVIORAL"
    FUNCTIONAL = "FUNCTIONAL"
    TRANSITION = "TRANSITION"


class MasteryTier(str, Enum):
    INSUFFICIENT_PROGRESS = "INSUFFICIENT_PROGRESS"
    PROGRESSING = "PROGRESSING"
    MASTERED = "MASTERED"


class RelatedServiceStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class ServiceType(str, Enum):
    OT = "OT"
    PT = "PT"
    SPEECH = "SPEECH"
    COUNSELING = "COUNSELING"
    ORIENTATION_MOBILITY = "ORIENTATION_MOBILITY"


class LocationSetting(str, Enum):
    PULL_OUT = "PULL_OUT"
    PUSH_IN = "PUSH_IN"
    COMMUNITY = "COMMUNITY"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class TransitionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class TriennialStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ON_TRACK = "ON_TRACK"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"


class LreClassification(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    LRE_A = "LRE_A"
    LRE_B = "LRE_B"
    LRE_C = "LRE_C"


class GoalDisposition(str, Enum):
    MET = "MET"
    NOT_MET = "NOT_MET"


# Federal disability categories from PRD §3.2.
DISABILITY_CATEGORIES = frozenset({
    "SLD", "OHI", "ASD", "SI", "OI", "ED", "ID",
    "HI", "VI", "DB", "TBI", "MD", "DD",
})


# ---------------------------------------------------------------------------
# Entities carrying the four common properties (id + created_at +
# updated_at + version) — PRD §2.4
# ---------------------------------------------------------------------------
class District(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    current_date: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    district_id: str
    external_student_number: str
    date_of_birth: str
    parent_user_id: str
    current_iep_id: Optional[str]
    current_eligibility_evaluation_id: Optional[str]
    triennial_reevaluation_due_date: Optional[str]
    triennial_status: str
    requires_transition_plan: bool
    lre_classification: str
    created_at: str
    updated_at: str
    version: int


class EligibilityEvaluation(TypedDict, total=False):
    id: str
    student_id: str
    district_id: str
    evaluation_type: str
    is_reevaluation: bool
    requested_at: str
    consent_received_at: Optional[str]
    finalized_at: Optional[str]
    disability_categories: List[str]
    evaluator_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IEP(TypedDict, total=False):
    id: str
    student_id: str
    district_id: str
    meeting_held_at: str
    effective_start_date: str
    scheduled_review_date: str
    total_instructional_minutes_per_week: int
    total_school_day_minutes_per_week: int
    special_education_minutes_per_week: int
    lre_percentage_instructional: float
    lre_percentage_school_day: float
    requires_transition_plan: bool
    transition_plan_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IEPGoal(TypedDict, total=False):
    id: str
    iep_id: str
    student_id: str
    district_id: str
    domain: str
    description: str
    objectives: list
    mastery_score: float
    mastery_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RelatedService(TypedDict, total=False):
    id: str
    iep_id: str
    student_id: str
    district_id: str
    service_type: str
    minutes_per_week: int
    provider_user_id: str
    location_setting: str
    consent_id: Optional[str]
    total_prescribed_minutes_to_date: int
    total_delivered_minutes: int
    total_cancelled_minutes: int
    compensatory_minutes_owed: int
    utilization_percent: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceSession(TypedDict, total=False):
    id: str
    related_service_id: str
    iep_id: str
    student_id: str
    scheduled_start: str
    scheduled_end: str
    scheduled_minutes: int
    actual_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransitionPlan(TypedDict, total=False):
    id: str
    iep_id: str
    student_id: str
    post_secondary_goal: str
    required_courses: list
    outside_agency_referrals: list
    parent_invitation_documented: bool
    student_invitation_documented: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at ONLY (no updated_at, no version)
# PRD §2.4: "Two entity types are append-only event records and
# therefore do not carry updated_at or version: ParentalConsent ... and
# GoalProgressReport."
# ---------------------------------------------------------------------------
class ParentalConsent(TypedDict, total=False):
    id: str
    student_id: str
    district_id: str
    scope: str
    target_resource_type: str
    target_resource_id: str
    requested_at: str
    decided_at: Optional[str]
    withdrawn_at: Optional[str]
    parent_user_id: Optional[str]
    status: str
    created_at: str


class GoalProgressReport(TypedDict, total=False):
    id: str
    iep_goal_id: str
    iep_id: str
    student_id: str
    reporting_period_index: int
    reported_by_user_id: str
    objective_progress: list
    narrative: str
    created_at: str


__all__ = [
    "UserRole",
    "EvaluationStatus",
    "EvaluationType",
    "ConsentStatus",
    "ConsentScope",
    "IepStatus",
    "IepGoalStatus",
    "GoalDomain",
    "MasteryTier",
    "RelatedServiceStatus",
    "ServiceType",
    "LocationSetting",
    "SessionStatus",
    "TransitionPlanStatus",
    "TriennialStatus",
    "LreClassification",
    "GoalDisposition",
    "DISABILITY_CATEGORIES",
    "District",
    "Student",
    "EligibilityEvaluation",
    "IEP",
    "IEPGoal",
    "RelatedService",
    "ServiceSession",
    "TransitionPlan",
    "ParentalConsent",
    "GoalProgressReport",
]
