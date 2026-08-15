"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class CurriculumModuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CoachStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    EXITED = "EXITED"


class WorkshopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    WAITLISTED = "WAITLISTED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class CoachingCaseStatus(str, Enum):
    INTAKE = "INTAKE"
    PLAN_DRAFT = "PLAN_DRAFT"
    PLAN_ACTIVE = "PLAN_ACTIVE"
    ON_HOLD = "ON_HOLD"
    PLAN_STALLED = "PLAN_STALLED"
    COMPLETED = "COMPLETED"
    EXITED = "EXITED"


class GoalPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    SUPERSEDED = "SUPERSEDED"
    ACHIEVED = "ACHIEVED"


class MatchPoolStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class MatchEnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MATCH_PAUSED = "MATCH_PAUSED"
    GOAL_MET = "GOAL_MET"
    PAID_OUT = "PAID_OUT"
    FORFEITED = "FORFEITED"


class PartnerType(str, Enum):
    LENDER = "LENDER"
    ASSISTANCE_PROGRAM = "ASSISTANCE_PROGRAM"


class ReferralStatus(str, Enum):
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class FunderReportVariant(str, Enum):
    COHORT = "COHORT"
    ROLLING = "ROLLING"


class AttendanceOutcome(str, Enum):
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "ProgramAdmin"
    COACH = "Coach"
    PARTICIPANT = "Participant"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# Primary resources carry id + created_at + updated_at + version.
# Append-only / frozen resources (OutcomeSnapshot, FunderReport) carry only
# id + created_at.


class CurriculumModule(TypedDict, total=False):
    id: str
    module_code: str
    title: str
    session_count: int
    incentive_cents_per_hour: int
    completion_bonus_cents: int
    completion_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    max_caseload: int
    status: str
    certification_expires_at: Optional[str]
    active_caseload: int
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    annual_income_cents: int
    status: str
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class Workshop(TypedDict, total=False):
    id: str
    module_id: str
    coach_id: str
    location: str
    start_at: str
    end_at: str
    capacity: int
    confirmed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict, total=False):
    id: str
    workshop_id: str
    participant_id: str
    status: str
    waitlist_position: Optional[int]
    incentive_earned_cents: int
    created_at: str
    updated_at: str
    version: int


class CoachingCase(TypedDict, total=False):
    id: str
    participant_id: str
    coach_id: str
    intake_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GoalPlan(TypedDict, total=False):
    id: str
    case_id: str
    monthly_savings_goal_cents: int
    credit_score_target: int
    status: str
    plan_sequence: int
    created_at: str
    updated_at: str
    version: int


class OutcomeSnapshot(TypedDict, total=False):
    # Append-only log entry: id + created_at only; no updated_at, no version.
    id: str
    participant_id: str
    recorded_at: str
    credit_score: Optional[int]
    savings_balance_cents: Optional[int]
    created_at: str


class MatchPool(TypedDict, total=False):
    id: str
    name: str
    total_funded_cents: int
    income_threshold_cents: int
    match_ratio_below: float
    match_ratio_above: float
    per_participant_cap_cents: int
    uncommitted_cents: int
    paid_out_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MatchEnrollment(TypedDict, total=False):
    id: str
    participant_id: str
    pool_id: str
    goal_plan_id: str
    savings_goal_cents: int
    status: str
    total_deposited_cents: int
    accrued_unpaid_cents: int
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    participant_id: str
    coach_id: str
    partner_name: str
    partner_type: str
    status: str
    sent_at: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class FunderReport(TypedDict, total=False):
    # Computed once and frozen: id + created_at only; no updated_at, no version.
    id: str
    period_start: str
    period_end: str
    variant: str
    participants_measured: int
    avg_credit_delta_points: Optional[float]
    avg_savings_delta_cents: Optional[int]
    completions_count: int
    created_at: str


class IncentiveSummary(TypedDict, total=False):
    earned_cents: int
    provisional_cents: int
    attended_sessions: int
    registered_sessions: int
    completion_bonuses_earned_cents: int
