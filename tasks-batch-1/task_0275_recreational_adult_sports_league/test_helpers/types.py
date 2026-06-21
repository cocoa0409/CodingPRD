"""Domain types: entity TypedDicts, status enums, role enum.

All field names and enum strings are exact per the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    LEAGUE_ADMIN = "LeagueAdmin"
    TEAM_CAPTAIN = "TeamCaptain"
    REFEREE = "Referee"
    CONDUCT_OFFICER = "ConductOfficer"


# --------------------------------------------------------------------------
# Status / enum types
# --------------------------------------------------------------------------
class Sport(str, Enum):
    SOCCER = "SOCCER"
    BASKETBALL = "BASKETBALL"
    SOFTBALL = "SOFTBALL"
    VOLLEYBALL = "VOLLEYBALL"


class SeasonStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SCHEDULED = "SCHEDULED"
    IN_PLAY = "IN_PLAY"
    PLAYOFFS = "PLAYOFFS"
    COMPLETE = "COMPLETE"


class SkillTier(str, Enum):
    REC = "REC"
    INTERMEDIATE = "INTERMEDIATE"
    COMPETITIVE = "COMPETITIVE"


class StandingsTiebreaker(str, Enum):
    HEAD_TO_HEAD = "HEAD_TO_HEAD"
    POINT_DIFFERENTIAL = "POINT_DIFFERENTIAL"


class TeamStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    WITHDRAWN_LOCKED = "WITHDRAWN_LOCKED"
    WITHDRAWN = "WITHDRAWN"
    CANCELLED = "CANCELLED"


class RosterEntryState(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class RefereeAssignmentRole(str, Enum):
    HEAD = "HEAD"
    ASSISTANT = "ASSISTANT"
    SCOREKEEPER = "SCOREKEEPER"


class RefereeAssignmentState(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class GameScheduleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"
    FORFEITED = "FORFEITED"
    PLAYED = "PLAYED"
    CANCELLED = "CANCELLED"


class GameScoreStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"


class GameStage(str, Enum):
    REGULAR = "REGULAR"
    PLAYOFF = "PLAYOFF"


class PlayerSuspensionStatus(str, Enum):
    CLEAR = "CLEAR"
    WARNED = "WARNED"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class PaymentKind(str, Enum):
    FEE = "FEE"
    REFUND = "REFUND"


class PaymentReason(str, Enum):
    REGISTRATION = "REGISTRATION"
    FULL_WITHDRAWAL = "FULL_WITHDRAWAL"
    PARTIAL_WITHDRAWAL = "PARTIAL_WITHDRAWAL"
    NO_REFUND_WITHDRAWAL = "NO_REFUND_WITHDRAWAL"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"


class ConductSeverity(str, Enum):
    WARNING = "WARNING"
    YELLOW = "YELLOW"
    RED = "RED"
    ABUSE = "ABUSE"


class ConductReportStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true  -> id, created_at, updated_at, version
# common_fields: false -> id, created_at  ONLY (Payment)
# --------------------------------------------------------------------------
class Season(TypedDict):
    id: str
    name: str
    sport: str
    registration_opens_at: str
    registration_closes_at: str
    registration_status: str
    refund_full_cutoff_at: str
    refund_partial_pct: int
    clock_now: str
    created_at: str
    updated_at: str
    version: int


class Division(TypedDict):
    id: str
    season_id: str
    name: str
    skill_tier: str
    min_roster_size: int
    max_roster_size: int
    team_capacity: int
    registration_fee_cents: int
    confirmed_team_count: int
    standings_tiebreaker: str
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    division_id: str
    captain_player_id: str
    name: str
    status: str
    roster_size: int
    fee_charged_cents: int
    refund_issued_cents: int
    wins: int
    losses: int
    draws: int
    points: int
    points_for: int
    points_against: int
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    full_name: str
    email: str
    is_free_agent: bool
    conduct_points: int
    suspension_status: str
    suspended_until_game_index: int
    created_at: str
    updated_at: str
    version: int


class RosterEntry(TypedDict):
    id: str
    team_id: str
    player_id: str
    state: str
    is_captain: bool
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    field_count: int
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Referee(TypedDict):
    id: str
    full_name: str
    certified_sports: List[str]
    created_at: str
    updated_at: str
    version: int


class Game(TypedDict):
    id: str
    division_id: str
    home_team_id: str
    away_team_id: str
    venue_id: str
    field_index: int
    round_index: int
    stage: str
    starts_at: str
    ends_at: str
    schedule_status: str
    score_status: str
    home_score: Optional[int]
    away_score: Optional[int]
    forfeiting_team_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefereeAssignment(TypedDict):
    id: str
    game_id: str
    referee_id: str
    role: str
    state: str
    created_at: str
    updated_at: str
    version: int


# Payment: append-only ledger row — id + created_at only, NO updated_at / version.
class Payment(TypedDict):
    id: str
    team_id: str
    kind: str
    amount_cents: int
    status: str
    reason: str
    created_at: str


class ConductReport(TypedDict):
    id: str
    game_id: str
    player_id: str
    severity: str
    status: str
    points: int
    created_at: str
    updated_at: str
    version: int
