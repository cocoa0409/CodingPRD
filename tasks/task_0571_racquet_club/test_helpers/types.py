"""Domain types: entity TypedDicts, status enums, role enum.

All types are derived from the Racquet Club API PRD (§2, §3). Every entity carries
the common audit fields id, created_at, updated_at, version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    MEMBER = "Member"
    PRO = "Pro"
    FRONT_DESK = "FrontDesk"


class CourtStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CANCELLED = "CANCELLED"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class LessonStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class CompetitionStatus(str, Enum):
    REGISTRATION = "REGISTRATION"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ParticipantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ELIMINATED = "ELIMINATED"


class StringingJobStatus(str, Enum):
    RECEIVED = "RECEIVED"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    CANCELLED = "CANCELLED"


class Court(TypedDict):
    id: str
    name: str
    surface: str
    location_type: str
    hourly_rate_cents: int
    has_ball_machine: bool
    ball_machine_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    name: str
    tier: str
    monthly_fee_cents: int
    monthly_court_credits: int
    peak_access: bool
    guest_fee_cents: int
    freeze_limit: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    full_name: str
    email: str
    status: str
    no_show_strikes: int
    account_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    member_id: str
    plan_id: str
    status: str
    court_credits_remaining: int
    estimated_period_fee_cents: int
    freeze_count: int
    current_period_start: str
    current_period_end: str
    frozen_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    court_id: str
    member_id: str
    start_time: str
    end_time: str
    guest_count: int
    actual_guest_count: Optional[int]
    uses_ball_machine: bool
    is_peak: bool
    credits_used: int
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Pro(TypedDict):
    id: str
    full_name: str
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lesson(TypedDict):
    id: str
    pro_id: str
    court_id: str
    kind: str
    start_time: str
    end_time: str
    capacity: int
    enrolled_count: int
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    lesson_id: str
    member_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Competition(TypedDict):
    id: str
    name: str
    format: str
    draw_size: Optional[int]
    entry_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    competition_id: str
    member_id: str
    seed: Optional[int]
    bracket_slot: Optional[int]
    ladder_rank: Optional[int]
    wins: int
    losses: int
    points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class StringingJob(TypedDict):
    id: str
    member_id: str
    racquet_label: str
    string_type: str
    tension: int
    price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
