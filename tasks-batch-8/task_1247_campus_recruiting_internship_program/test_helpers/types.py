"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    SELECTION = "SELECTION"
    OFFER_PERIOD = "OFFER_PERIOD"
    INTERN_ACTIVE = "INTERN_ACTIVE"
    CLOSED = "CLOSED"


class SchoolTier(str, Enum):
    CORE = "CORE"
    TARGET = "TARGET"
    EXPLORATORY = "EXPLORATORY"


class StipendRegion(str, Enum):
    METRO = "METRO"
    REGIONAL = "REGIONAL"
    REMOTE = "REMOTE"


class SchoolTargetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DROPPED = "DROPPED"


class EventType(str, Enum):
    CAREER_FAIR = "CAREER_FAIR"
    INFO_SESSION = "INFO_SESSION"
    RESUME_DROP = "RESUME_DROP"


class CampusEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SHORTLISTED = "SHORTLISTED"
    INTERVIEW_SCHEDULED = "INTERVIEW_SCHEDULED"
    DECISION_PENDING = "DECISION_PENDING"
    OFFER_PENDING = "OFFER_PENDING"
    ACCEPTED = "ACCEPTED"
    SCREENED_OUT = "SCREENED_OUT"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class InterviewDayStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"


class InterviewSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class OfferStatus(str, Enum):
    DRAFT = "DRAFT"
    EXTENDED = "EXTENDED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    RESCINDED = "RESCINDED"


class DisbursementStatus(str, Enum):
    RESERVED = "RESERVED"
    DISBURSED = "DISBURSED"
    RELEASED = "RELEASED"


class InternProjectStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    UNASSIGNED = "UNASSIGNED"


class ReturnOfferDecision(str, Enum):
    NONE = "NONE"
    EXTENDED = "EXTENDED"
    NO_OFFER = "NO_OFFER"


class ReturnOfferOutcome(str, Enum):
    NONE = "NONE"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class InternEvalType(str, Enum):
    MID = "MID"
    FINAL = "FINAL"


class Recommendation(str, Enum):
    STRONG_HIRE = "STRONG_HIRE"
    HIRE = "HIRE"
    LEAN_NO = "LEAN_NO"
    NO_HIRE = "NO_HIRE"


class DeadlinePolicyMode(str, Enum):
    WALL_CLOCK = "WALL_CLOCK"
    BUSINESS_HOURS = "BUSINESS_HOURS"


class UserRole(str, Enum):
    RECRUITING_ADMIN = "RecruitingAdmin"
    RECRUITER = "Recruiter"
    CANDIDATE = "Candidate"
    EVALUATOR = "Evaluator"
    MENTOR = "Mentor"
    ANONYMOUS = "Anonymous"


class RecruitingSeason(TypedDict, total=False):
    id: str
    name: str
    status: str
    application_open_at: str
    application_close_at: str
    interview_window_start_at: str
    interview_window_end_at: str
    offer_window_open_at: str
    offer_window_close_at: str
    exploding_offer_hours_default: int
    deadline_policy_mode: str
    max_extension_hours: int
    shortlist_score_threshold: int
    stipend_budget_cents: int
    stipend_reserved_cents: int
    stipend_disbursed_cents: int
    applications_total_count: int
    offers_extended_count: int
    offers_accepted_count: int
    completed_assignments_count: int
    return_offers_extended_count: int
    return_offers_accepted_count: int
    created_at: str
    updated_at: str
    version: int


class SchoolTarget(TypedDict, total=False):
    id: str
    season_id: str
    school_name: str
    tier: str
    application_cap: int
    stipend_region: str
    exploding_offer_hours_override: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CampusEvent(TypedDict, total=False):
    id: str
    season_id: str
    school_target_id: str
    event_type: str
    start_at: str
    end_at: str
    status: str
    resume_count: int
    created_at: str
    updated_at: str
    version: int


class Candidate(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    expected_graduation_date: str
    is_alumnus: bool
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    season_id: str
    candidate_id: str
    school_target_id: str
    status: str
    referral_flag: bool
    prior_internship_count: int
    relocation_distance_miles: int
    screening_score_provisional: int
    screening_score_final: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    season_id: str
    full_name: str
    email: str
    alma_mater_school_name: Optional[str]
    daily_slot_limit: int
    max_interns: int
    can_evaluate: bool
    can_mentor: bool
    calibrated: bool
    assigned_intern_count: int
    created_at: str
    updated_at: str
    version: int


class InterviewDay(TypedDict, total=False):
    id: str
    season_id: str
    window_start_at: str
    window_end_at: str
    capacity: int
    booked_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InterviewSlot(TypedDict, total=False):
    id: str
    interview_day_id: str
    application_id: str
    evaluator_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Evaluation(TypedDict, total=False):
    id: str
    interview_slot_id: str
    evaluator_id: str
    score: int
    recommendation: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    application_id: str
    status: str
    weekly_rate_cents: int
    duration_weeks: int
    sign_on_bonus_cents: int
    total_comp_cents: int
    policy_hours_snapshot: Optional[int]
    extended_at: Optional[str]
    deadline_at: Optional[str]
    extension_hours_granted: int
    stipend_amount_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class StipendDisbursement(TypedDict, total=False):
    id: str
    offer_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InternProject(TypedDict, total=False):
    id: str
    season_id: str
    title: str
    capacity: int
    assigned_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProjectAssignment(TypedDict, total=False):
    id: str
    application_id: str
    intern_project_id: str
    mentor_id: str
    status: str
    return_offer_decision: str
    return_offer_outcome: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only record; carries ONLY id + created_at
class InternEvaluation(TypedDict, total=False):
    id: str
    project_assignment_id: str
    eval_type: str
    rating: int
    would_rehire: bool
    submitted_by_mentor_id: str
    created_at: str
