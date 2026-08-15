"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly. Every resource carries the four
standard system-managed fields (id, created_at, updated_at, version) per the
PRD common-resource-properties section.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    FINALIZED = "FINALIZED"


class DivisionCategory(str, Enum):
    CHEER = "CHEER"
    DANCE = "DANCE"


class TeamRegStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    CHECKED_IN = "CHECKED_IN"
    COMPETED = "COMPETED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class TeamMusicStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"


class RosterEntryEligibility(str, Enum):
    ACTIVE = "ACTIVE"
    INELIGIBLE = "INELIGIBLE"


class PerformanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PERFORMED = "PERFORMED"
    SCORED = "SCORED"
    OFFICIAL = "OFFICIAL"
    EXCLUDED = "EXCLUDED"
    CANCELLED = "CANCELLED"


class ScoreSheetStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LOCKED = "LOCKED"


class DeductionType(str, Enum):
    SAFETY = "SAFETY"
    TIME = "TIME"
    BOUNDARY = "BOUNDARY"


class DeductionStatus(str, Enum):
    APPLIED = "APPLIED"
    UNDER_APPEAL = "UNDER_APPEAL"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    VOIDED = "VOIDED"


class DeductionSource(str, Enum):
    SYSTEM = "SYSTEM"
    MANUAL = "MANUAL"


class AppealStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class BidKind(str, Enum):
    PAID = "PAID"
    AT_LARGE = "AT_LARGE"


class BidStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class MusicSubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    FLAGGED = "FLAGGED"
    SUPERSEDED = "SUPERSEDED"


class TicketOrderTier(str, Enum):
    ADVANCE = "ADVANCE"
    GATE = "GATE"


class TicketOrderStatus(str, Enum):
    HELD = "HELD"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


class WarmUpAssignmentStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class WarmUpAssignmentSource(str, Enum):
    SYSTEM = "SYSTEM"
    MANUAL = "MANUAL"


class UserRole(str, Enum):
    EVENT_DIRECTOR = "EventDirector"
    TEAM_COACH = "TeamCoach"
    JUDGE = "Judge"
    HEAD_JUDGE = "HeadJudge"
    SAFETY_JUDGE = "SafetyJudge"
    MUSIC_COMPLIANCE = "MusicCompliance"
    ELIGIBILITY_OFFICER = "EligibilityOfficer"
    SPECTATOR = "Spectator"


class Event(TypedDict, total=False):
    id: str
    name: str
    venue_name: str
    start_date: str
    end_date: str
    age_reference_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Division(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    category: str
    level: int
    min_age: int
    max_age: int
    min_athletes: int
    max_athletes: int
    routine_time_limit_seconds: int
    warmup_duration_seconds: int
    warmup_mats: List[str]
    schedule_start_at: str
    judge_ids: List[str]
    time_deduction_per_second: float
    safety_deduction_points: float
    boundary_deduction_points: float
    paid_bid_count: int
    at_large_bid_count: int
    bid_pool_available: int
    scheduled: bool
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    event_id: str
    division_id: str
    name: str
    organization: str
    category: str
    level: int
    coach_user_id: str
    reg_status: str
    music_status: str
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict, total=False):
    id: str
    full_name: str
    date_of_birth: str
    created_at: str
    updated_at: str
    version: int


class RosterEntry(TypedDict, total=False):
    id: str
    team_id: str
    athlete_id: str
    bib_number: int
    eligibility_status: str
    checked_in: bool
    removed: bool
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict, total=False):
    id: str
    full_name: str
    certified_levels: List[int]
    created_at: str
    updated_at: str
    version: int


class Performance(TypedDict, total=False):
    id: str
    team_id: str
    division_id: str
    performance_order: int
    scheduled_start: str
    actual_duration_seconds: int
    boundary_violations: int
    status: str
    provisional_score: Optional[float]
    official_score: Optional[float]
    rank_in_division: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ScoreSheet(TypedDict, total=False):
    id: str
    performance_id: str
    judge_id: str
    building_difficulty: float
    building_execution: float
    tumbling_difficulty: float
    overall_impression: float
    status: str
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deduction(TypedDict, total=False):
    id: str
    performance_id: str
    type: str
    quantity: int
    skill_tier: Optional[int]
    rate_applied: float
    points: float
    source: str
    applied_by_judge_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    deduction_id: str
    round: int
    note: str
    video_ref: str
    status: str
    decided_by_judge_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    division_id: str
    team_id: str
    kind: str
    status: str
    rank_at_offer: int
    offered_at: str
    acceptance_deadline: str
    created_at: str
    updated_at: str
    version: int


class MusicSubmission(TypedDict, total=False):
    id: str
    team_id: str
    track_count: int
    license_provider: str
    license_reference: str
    status: str
    flag_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    starts_at: str
    ends_at: str
    capacity: int
    seats_held: int
    seats_sold: int
    seats_available: int
    created_at: str
    updated_at: str
    version: int


class TicketOrder(TypedDict, total=False):
    id: str
    session_id: str
    purchaser_user_id: str
    quantity: int
    tier: str
    unit_price_cents: int
    discount_cents: int
    total_cents: int
    status: str
    hold_expires_at: str
    created_at: str
    updated_at: str
    version: int


class WarmUpAssignment(TypedDict, total=False):
    id: str
    event_id: str
    team_id: str
    mat: str
    starts_at: str
    ends_at: str
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int
