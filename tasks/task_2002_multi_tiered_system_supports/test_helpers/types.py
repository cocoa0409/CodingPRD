"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.6, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class WindowKind(str, Enum):
    FALL = "FALL"
    WINTER = "WINTER"
    SPRING = "SPRING"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SCORED = "SCORED"


class Subject(str, Enum):
    READING = "READING"
    MATH = "MATH"


class Tier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ProbeFrequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


class SessionOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    STUDENT_ABSENT = "STUDENT_ABSENT"
    STAFF_ABSENT = "STAFF_ABSENT"
    CANCELLED = "CANCELLED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXIT_RESPONSIVE = "EXIT_RESPONSIVE"
    EXIT_MOVED = "EXIT_MOVED"
    EXIT_SPED_REFERRAL = "EXIT_SPED_REFERRAL"
    EXIT_NO_PROGRESS = "EXIT_NO_PROGRESS"
    CANCELLED = "CANCELLED"


class MovementStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RATIFIED = "RATIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONVENED = "CONVENED"
    MINUTED = "MINUTED"


class ReferralStatus(str, Enum):
    PENDING_CONSENT = "PENDING_CONSENT"
    CONSENTED = "CONSENTED"
    EVAL_IN_PROGRESS = "EVAL_IN_PROGRESS"
    ELIGIBLE = "ELIGIBLE"
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    WITHDRAWN = "WITHDRAWN"


class SlopeDecision(str, Enum):
    RESPONSIVE = "RESPONSIVE"
    NON_RESPONSIVE = "NON_RESPONSIVE"


class SubgroupCode(str, Enum):
    ELL = "ELL"
    FRL = "FRL"
    IEP = "IEP"
    BLACK = "BLACK"
    HISPANIC = "HISPANIC"
    WHITE = "WHITE"
    ASIAN = "ASIAN"
    MULTI = "MULTI"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISTRICT_COORDINATOR = "DistrictCoordinator"
    SCHOOL_REGISTRAR = "SchoolRegistrar"
    TEACHER = "Teacher"
    INTERVENTIONIST_ROLE = "InterventionistRole"
    TEAM_LEAD = "TeamLead"
    SPED_DIRECTOR = "SpEdDirector"


# --- Entities carrying the standard system-managed fields (PRD §2.6):
# id + created_at + updated_at + version ---


class District(TypedDict):
    id: str
    name: str
    academic_year: str
    sped_referral_min_weeks: int
    fidelity_threshold_pct: int
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    district_id: str
    name: str
    grade_span_low: int
    grade_span_high: int
    created_at: str
    updated_at: str
    version: int


class ScreeningWindow(TypedDict):
    id: str
    school_id: str
    window_kind: str
    opens_on: str
    closes_on: str
    status: str
    screened_student_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    school_id: str
    full_name: str
    grade_level: int
    subgroup_codes: List[str]
    current_tier: str
    weeks_at_tier3_unresponsive: int
    created_at: str
    updated_at: str
    version: int


class InterventionCatalogEntry(TypedDict):
    id: str
    district_id: str
    title: str
    subject: str
    tier_target: str
    grade_min: int
    grade_max: int
    session_minutes: int
    sessions_per_week: int
    probe_frequency: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Interventionist(TypedDict):
    id: str
    school_id: str
    full_name: str
    weekly_minute_capacity: int
    committed_minutes_per_week: int
    subjects: List[str]
    created_at: str
    updated_at: str
    version: int


class StudentPlan(TypedDict):
    id: str
    student_id: str
    catalog_entry_id: str
    interventionist_id: str
    tier_at_start: str
    started_on: str
    weekly_minute_cost: int
    probe_due_on: str
    fidelity_pct: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TierMovement(TypedDict):
    id: str
    student_id: str
    from_tier: str
    to_tier: str
    rationale: str
    decided_at_meeting_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TeamMeeting(TypedDict):
    id: str
    school_id: str
    scheduled_on: str
    status: str
    minuted_movement_count: int
    created_at: str
    updated_at: str
    version: int


class SpedReferral(TypedDict):
    id: str
    student_id: str
    triggered_plan_id: str
    consent_received_on: Optional[str]
    evaluation_due_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Immutable / append-only resources (PRD §2.6): carry ONLY id + created_at;
# updated_at and version are absent. ---


class BenchmarkCutPoint(TypedDict):
    id: str
    school_id: str
    window_kind: str
    grade_level: int
    subject: str
    tier2_max_score: int
    tier3_max_score: int
    created_at: str


class ScreeningScore(TypedDict):
    id: str
    window_id: str
    student_id: str
    subject: str
    raw_score: int
    risk_band: str
    created_at: str


class ProgressProbe(TypedDict):
    id: str
    plan_id: str
    administered_on: str
    score: int
    aimline_score: int
    slope_decision: str
    created_at: str


class InterventionSession(TypedDict):
    id: str
    plan_id: str
    scheduled_on: str
    minutes: int
    outcome: str
    created_at: str
