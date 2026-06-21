"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's common-resource rules (§2.4): Leagues, Officials,
Games, CrewSlots, Assignments, Availabilities, SeasonLedgers and PenaltyAppeals
carry id/created_at/updated_at/version; ConflictDeclaration and Evaluation are
immutable and carry only id/created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ──────────────────────────────────────────────────────────

class LeagueStatus(str, Enum):
    SETUP = "SETUP"
    OPEN = "OPEN"
    POSTSEASON = "POSTSEASON"
    ARCHIVED = "ARCHIVED"


class OfficialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OfficialRank(str, Enum):
    ROOKIE = "ROOKIE"
    CERTIFIED = "CERTIFIED"
    SENIOR = "SENIOR"
    MASTER = "MASTER"


class GameStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    STAFFED = "STAFFED"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CrewSlotStatus(str, Enum):
    VACANT = "VACANT"
    OFFERED = "OFFERED"
    FILLED = "FILLED"
    RELEASED = "RELEASED"


class CrewSlotPosition(str, Enum):
    REFEREE = "REFEREE"
    ASSISTANT = "ASSISTANT"
    OBSERVER = "OBSERVER"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class AvailabilityKind(str, Enum):
    AVAILABLE = "AVAILABLE"
    BLACKOUT = "BLACKOUT"


class AvailabilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class ConflictScope(str, Enum):
    TEAM = "TEAM"
    OFFICIAL = "OFFICIAL"


class PenaltyAppealStatus(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class Sport(str, Enum):
    BASKETBALL = "BASKETBALL"
    SOCCER = "SOCCER"
    HOCKEY = "HOCKEY"
    FOOTBALL = "FOOTBALL"


class UserRole(str, Enum):
    LEAGUE_ADMIN = "LeagueAdmin"
    ASSIGNOR = "Assignor"
    OFFICIAL = "Official"
    EVALUATOR = "Evaluator"


# ─── Entity TypedDicts (common_fields: true → id/created_at/updated_at/version)

class League(TypedDict):
    id: str
    name: str
    sport: str
    base_game_fee_cents: int
    mileage_rate_cents_per_mile: int
    postseason_min_games: int
    postseason_min_rating: float
    postseason_max_noshows: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Official(TypedDict):
    id: str
    league_id: str
    full_name: str
    rank: str
    home_lat: float
    home_lon: float
    max_travel_miles: float
    status: str
    games_worked_count: int
    noshow_count: int
    penalty_points: int
    mean_rating: Optional[float]
    reliability_score: int
    postseason_eligible: bool
    created_at: str
    updated_at: str
    version: int


class Game(TypedDict):
    id: str
    league_id: str
    home_team: str
    away_team: str
    venue_lat: float
    venue_lon: float
    start_utc: str
    duration_minutes: int
    required_crew_size: int
    is_postseason: bool
    status: str
    crew_filled_count: int
    settlement_total_cents: int
    created_at: str
    updated_at: str
    version: int


class CrewSlot(TypedDict):
    id: str
    game_id: str
    position: str
    slot_fee_multiplier: float
    status: str
    current_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    crew_slot_id: str
    game_id: str
    official_id: str
    status: str
    distance_miles: float
    provisional_pay_cents: int
    final_pay_cents: int
    mileage_cents: int
    penalty_assessed_points: int
    created_at: str
    updated_at: str
    version: int


class Availability(TypedDict):
    id: str
    official_id: str
    window_start_utc: str
    window_end_utc: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonLedger(TypedDict):
    id: str
    league_id: str
    official_id: str
    penalty_points: int
    total_pay_accrued_cents: int
    total_mileage_accrued_cents: int
    created_at: str
    updated_at: str
    version: int


class PenaltyAppeal(TypedDict):
    id: str
    assignment_id: str
    official_id: str
    reason: str
    status: str
    reversed_points: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entities (common_fields: false → id/created_at only) ───────

class ConflictDeclaration(TypedDict):
    id: str
    official_id: str
    scope: str
    team_name: Optional[str]
    peer_official_id: Optional[str]
    created_at: str


class Evaluation(TypedDict):
    id: str
    assignment_id: str
    official_id: str
    score: float
    comment: Optional[str]
    created_at: str
