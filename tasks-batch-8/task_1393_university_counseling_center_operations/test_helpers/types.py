"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    STUDENT = "Student"
    FRONT_DESK = "FrontDesk"
    TRIAGE_SCREENER = "TriageScreener"
    COUNSELOR = "Counselor"
    REFERRAL_COORDINATOR = "ReferralCoordinator"
    CLINICAL_DIRECTOR = "ClinicalDirector"
    REGISTRAR = "Registrar"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    LEAVE_OF_ABSENCE = "LEAVE_OF_ABSENCE"
    WITHDRAWN = "WITHDRAWN"
    GRADUATED = "GRADUATED"


class FundingModel(str, Enum):
    STUDENT_FEE = "STUDENT_FEE"
    INSURANCE = "INSURANCE"
    SPLIT = "SPLIT"


class BookingPosture(str, Enum):
    CLEAR = "CLEAR"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class RiskBand(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IntakeDisposition(str, Enum):
    PENDING = "PENDING"
    SHORT_TERM_CARE = "SHORT_TERM_CARE"
    COMMUNITY_REFERRAL = "COMMUNITY_REFERRAL"
    CRISIS_PROTOCOL = "CRISIS_PROTOCOL"


class EpisodeStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    REFERRED_OUT = "REFERRED_OUT"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    COMPLETED = "COMPLETED"
    CANCELLED_TIMELY = "CANCELLED_TIMELY"
    CANCELLED_LATE = "CANCELLED_LATE"
    NO_SHOW_CHARGED = "NO_SHOW_CHARGED"
    NO_SHOW_EXCUSED = "NO_SHOW_EXCUSED"


class GroupProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class GroupEnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    DROPPED = "DROPPED"
    REMOVED_RISK = "REMOVED_RISK"


class CrisisShiftStatus(str, Enum):
    UNCLAIMED = "UNCLAIMED"
    CLAIMED = "CLAIMED"
    RELEASED = "RELEASED"
    COVERED = "COVERED"


class CrisisVisitStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_ROOM = "IN_ROOM"
    STABILIZED = "STABILIZED"
    ESCALATED = "ESCALATED"
    DISPOSITIONED = "DISPOSITIONED"


class CrisisVisitDisposition(str, Enum):
    NONE = "NONE"
    RETURN_TO_CARE = "RETURN_TO_CARE"
    COMMUNITY_REFERRAL = "COMMUNITY_REFERRAL"
    EMERGENCY_TRANSPORT = "EMERGENCY_TRANSPORT"


class ReferralStatus(str, Enum):
    PENDING = "PENDING"
    MATCHED = "MATCHED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    COMPLETED = "COMPLETED"
    LAPSED = "LAPSED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


# --- Entities carrying the full common-field set (id, created_at, updated_at, version) ---

class Student(TypedDict, total=False):
    id: str
    student_number: str
    full_name: str
    enrollment_status: str
    funding_model: str
    academic_record_flags: List[str]
    no_show_strike_count: int
    strike_reset_anchor: str
    booking_posture: str
    created_at: str
    updated_at: str
    version: int


class Counselor(TypedDict, total=False):
    id: str
    license_id: str
    full_name: str
    specialties: List[str]
    weekly_individual_capacity: int
    max_caseload_risk_points: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class CareEpisode(TypedDict, total=False):
    id: str
    student_id: str
    primary_counselor_id: str
    intake_assessment_id: Optional[str]
    academic_term: str
    session_limit: int
    sessions_consumed: int
    status: str
    prior_episode_id: Optional[str]
    exemption_granted: bool
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    episode_id: str
    counselor_id: str
    starts_at: str
    duration_minutes: int
    status: str
    cancellation_reason: Optional[str]
    billed_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class GroupProgram(TypedDict, total=False):
    id: str
    title: str
    facilitator_id: str
    capacity: int
    meeting_day: str
    starts_at: str
    weeks: int
    risk_band_ceiling: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrisisShift(TypedDict, total=False):
    id: str
    coverage_date: str
    shift_kind: str
    starts_at: str
    ends_at: str
    claimed_by_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CrisisVisit(TypedDict, total=False):
    id: str
    student_id: str
    shift_id: str
    presenting_risk_band: str
    status: str
    disposition: str
    created_at: str
    updated_at: str
    version: int


class CommunityReferral(TypedDict, total=False):
    id: str
    student_id: str
    episode_id: Optional[str]
    provider_name: Optional[str]
    required_specialty: str
    status: str
    rematch_count: int
    created_at: str
    updated_at: str
    version: int


class SemesterPolicy(TypedDict, total=False):
    id: str
    academic_term: str
    base_session_limit: int
    no_show_strike_limit: int
    late_cancel_window_hours: int
    policy_status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only resources: only id + created_at, NO updated_at, NO version ---

class IntakeAssessment(TypedDict, total=False):
    id: str
    student_id: str
    screener_id: str
    phq9_score: int
    gad7_score: int
    ideation_flag: bool
    recent_attempt_flag: bool
    risk_points: int
    risk_band: str
    disposition: str
    created_at: str


class GroupEnrollment(TypedDict, total=False):
    id: str
    program_id: str
    student_id: str
    status: str
    created_at: str


class OutcomeMeasure(TypedDict, total=False):
    id: str
    episode_id: str
    instrument: str
    phase: str
    score: int
    created_at: str


class ClinicalNote(TypedDict, total=False):
    id: str
    session_id: str
    author_id: str
    body: str
    created_at: str
