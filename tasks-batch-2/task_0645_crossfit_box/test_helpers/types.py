"""Domain types: entity TypedDicts, status enums, role enum.

All ten primary resources carry the standard system-managed fields
id, created_at, updated_at, and version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum -------------------------------------------------------------

class UserRole(str, Enum):
    BOX_MANAGER = "BoxManager"
    COACH = "Coach"
    MEMBER = "Member"
    ANONYMOUS = "Anonymous"


# --- Status / enum value sets ---------------------------------------------

class PlanType(str, Enum):
    UNLIMITED = "UNLIMITED"
    PUNCH = "PUNCH"


class MembershipStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELLED = "CANCELLED"


class TrackType(str, Enum):
    FOUNDATIONS = "FOUNDATIONS"
    REGULAR = "REGULAR"
    COMPETITION = "COMPETITION"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ReservationKind(str, Enum):
    MEMBERSHIP = "MEMBERSHIP"
    DROP_IN = "DROP_IN"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    ATTENDED = "ATTENDED"


class BenchmarkName(str, Enum):
    FRAN = "FRAN"
    GRACE = "GRACE"
    MURPH = "MURPH"
    BACK_SQUAT_1RM = "BACK_SQUAT_1RM"
    DEADLIFT_1RM = "DEADLIFT_1RM"


class MetricKind(str, Enum):
    TIME_SECONDS = "TIME_SECONDS"
    LOAD_KG = "LOAD_KG"


class TeamStatus(str, Enum):
    FORMING = "FORMING"
    LOCKED = "LOCKED"
    DISBANDED = "DISBANDED"


class TeamMemberStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REMOVED = "REMOVED"


# --- Entity TypedDicts (all common_fields: true) --------------------------

class MembershipPlan(TypedDict):
    id: str
    name: str
    plan_type: str
    monthly_fee_cents: int
    punch_count: Optional[int]
    commitment_months: int
    early_termination_fee_cents: int
    requires_foundations: bool
    active: bool
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    email: str
    full_name: str
    home_box_member: bool
    no_show_strikes: int
    reservation_suspended: bool
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    member_id: str
    plan_id: str
    status: str
    punches_remaining: Optional[int]
    foundations_completed: bool
    contract_start_date: Optional[str]
    commitment_end_date: Optional[str]
    freeze_started_at: Optional[str]
    total_frozen_days: int
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class ProgramTrack(TypedDict):
    id: str
    name: str
    track_type: str
    head_coach_id: str
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict):
    id: str
    full_name: str
    email: str
    certified: bool
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    track_id: str
    coach_id: str
    starts_at: str
    duration_minutes: int
    capacity: int
    drop_in_fee_cents: int
    status: str
    seats_reserved: int
    waitlist_count: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    session_id: str
    member_id: str
    membership_id: Optional[str]
    reservation_kind: str
    status: str
    waitlist_position: Optional[int]
    drop_in_fee_charged_cents: int
    punch_consumed: bool
    created_at: str
    updated_at: str
    version: int


class BenchmarkResult(TypedDict):
    id: str
    member_id: str
    benchmark_name: str
    metric_kind: str
    value: float
    recorded_at: str
    verified: bool
    is_pr: bool
    created_at: str
    updated_at: str
    version: int


class CompetitionTeam(TypedDict):
    id: str
    name: str
    captain_member_id: str
    max_roster_size: int
    roster_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TeamMember(TypedDict):
    id: str
    team_id: str
    member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int
