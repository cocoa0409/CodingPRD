"""Domain types: entity TypedDicts, status enums, role enum (PRD §3).

Field names are PRD-exact. The `ProgressReport` resource is immutable
(PRD §2.4): it carries only `id` and `created_at` — no `updated_at`, no
`version`. Every other entity carries the four common fields.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    SPECIAL_ED_ADMIN = "SpecialEdAdmin"
    CASE_MANAGER = "CaseManager"
    EVALUATOR = "Evaluator"
    PARENT = "Parent"


# ─── Status enums (PRD §3) ──────────────────────────────────────
class StudentEligibilityStatus(str, Enum):
    NOT_EVALUATED = "NOT_EVALUATED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class DisabilityCategory(str, Enum):
    SLD = "SLD"
    AUTISM = "AUTISM"
    SPEECH_LANGUAGE = "SPEECH_LANGUAGE"
    OHI = "OHI"
    EMOTIONAL = "EMOTIONAL"
    INTELLECTUAL = "INTELLECTUAL"


class EvaluationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONSENT_PENDING = "CONSENT_PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    FINALIZED = "FINALIZED"


class EvalType(str, Enum):
    INITIAL = "INITIAL"
    TRIENNIAL = "TRIENNIAL"


class EvaluationOutcome(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"


class IEPStatus(str, Enum):
    DRAFT = "DRAFT"
    MEETING_HELD = "MEETING_HELD"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    ARCHIVED = "ARCHIVED"


class LRESetting(str, Enum):
    FULL_INCLUSION = "FULL_INCLUSION"
    RESOURCE = "RESOURCE"
    SEPARATE_CLASS = "SEPARATE_CLASS"


class GoalDomain(str, Enum):
    READING = "READING"
    MATH = "MATH"
    WRITING = "WRITING"
    COMMUNICATION = "COMMUNICATION"
    BEHAVIOR = "BEHAVIOR"
    MOTOR = "MOTOR"


class GoalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MET = "MET"
    DISCONTINUED = "DISCONTINUED"


class ServiceType(str, Enum):
    OT = "OT"
    PT = "PT"
    SPEECH = "SPEECH"


class RelatedServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class ConsentType(str, Enum):
    EVALUATION = "EVALUATION"
    PLACEMENT = "PLACEMENT"


class ConsentStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class ConsentDecision(str, Enum):
    GRANT = "GRANT"
    DENY = "DENY"


class TransitionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ADOPTED = "ADOPTED"


# ─── Entity TypedDicts (PRD §3) ─────────────────────────────────
class Student(TypedDict):
    id: str
    full_name: str
    date_of_birth: str
    grade_level: int
    eligibility_status: str
    disability_category: Optional[str]
    active_iep_id: Optional[str]
    next_reeval_due_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict):
    id: str
    student_id: str
    eval_type: str
    cognitive_score: float
    academic_score: float
    adaptive_score: float
    proposed_category: str
    status: str
    composite_eligibility_score: Optional[float]
    outcome: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IEP(TypedDict):
    id: str
    student_id: str
    school_day_minutes: int
    annual_review_due_date: str
    status: str
    lre_general_ed_pct: float
    lre_setting: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Goal(TypedDict):
    id: str
    iep_id: str
    domain: str
    baseline_value: float
    target_value: float
    status: str
    latest_progress_pct: float
    cumulative_progress_pct: float
    created_at: str
    updated_at: str
    version: int


# ProgressReport: immutable, common_fields=false (PRD §2.4) — id + created_at only.
class ProgressReport(TypedDict):
    id: str
    goal_id: str
    reporting_period: int
    measured_value: float
    created_at: str


class RelatedService(TypedDict):
    id: str
    iep_id: str
    service_type: str
    minutes_per_week: int
    delivered_in_general_ed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsentRequest(TypedDict):
    id: str
    student_id: str
    iep_id: Optional[str]
    consent_type: str
    status: str
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransitionPlan(TypedDict):
    id: str
    iep_id: str
    postsecondary_goal: str
    services_summary: str
    status: str
    created_at: str
    updated_at: str
    version: int
