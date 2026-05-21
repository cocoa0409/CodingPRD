"""Domain types: entity TypedDicts, status enums, role enum.

Primary resources (Season, Player, Guardian, Team, Coach, Referee, Game,
VolunteerShift) carry the audit trio per PRD §2.4: id + created_at +
updated_at + version.

AuditEvent is the only append-only record (PRD §2.4 / §3.8): "the
`AuditEvent` rows ... carry only `id` and `created_at`, with no
`updated_at` and no `version`, because they are append-only and never
re-edited." Its TypedDict therefore intentionally omits updated_at and
version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ===========================================================================
# Role enum — PRD §2.1
# ===========================================================================
class UserRole(str, Enum):
    LEAGUE_ADMIN = "LeagueAdmin"
    COACH = "Coach"
    REFEREE = "Referee"
    GUARDIAN = "Guardian"


# ===========================================================================
# Status enums — PRD §3
# ===========================================================================
class SeasonStatus(str, Enum):
    DRAFT_OPEN = "DRAFT_OPEN"
    REGULAR_SEASON = "REGULAR_SEASON"
    PLAYOFFS = "PLAYOFFS"
    CLOSED = "CLOSED"


class AgeDivision(str, Enum):
    TBALL = "TBALL"
    MINORS = "MINORS"
    MAJORS = "MAJORS"
    INTERMEDIATE = "INTERMEDIATE"
    JUNIORS = "JUNIORS"


class PlayerStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    AGE_VERIFIED = "AGE_VERIFIED"
    EVALUATED = "EVALUATED"
    DRAFTED = "DRAFTED"
    WITHDRAWN = "WITHDRAWN"


class EvaluationTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    TIER_D = "TIER_D"


class VolunteerStatus(str, Enum):
    DEFICIENT = "DEFICIENT"
    ON_TRACK = "ON_TRACK"
    FULFILLED = "FULFILLED"


class GameStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    POSTPONED = "POSTPONED"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"


class GameType(str, Enum):
    REGULAR = "REGULAR"
    PLAYOFF = "PLAYOFF"


class PlayoffStatus(str, Enum):
    NOT_QUALIFIED = "NOT_QUALIFIED"
    QUALIFIED = "QUALIFIED"
    ELIMINATED = "ELIMINATED"
    CHAMPION = "CHAMPION"


class CertificationLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class VolunteerShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    APPROVED = "APPROVED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class VolunteerRole(str, Enum):
    SCOREKEEPER = "SCOREKEEPER"
    CONCESSIONS = "CONCESSIONS"
    FIELD_PREP = "FIELD_PREP"
    UMPIRE_ASSIST = "UMPIRE_ASSIST"
    SETUP_TEARDOWN = "SETUP_TEARDOWN"


class PostponeReason(str, Enum):
    RAIN = "RAIN"
    FIELD_UNAVAILABLE = "FIELD_UNAVAILABLE"
    SAFETY = "SAFETY"


# ===========================================================================
# Entity TypedDicts — primary resources carry audit trio (PRD §2.4).
# ===========================================================================
class Season(TypedDict, total=False):
    id: str
    name: str
    age_division: str
    min_birth_date: str
    max_birth_date: str
    regular_season_start: str
    regular_season_end: str
    playoff_cutoff_date: str
    status: str
    rainout_window_days: int
    volunteer_hours_required_per_family: float
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict, total=False):
    id: str
    season_id: str
    first_name: str
    last_name: str
    birth_date: str
    guardian_id: str
    birth_certificate_uri: Optional[str]
    evaluation_score: Optional[float]
    evaluation_tier: Optional[str]
    status: str
    team_id: Optional[str]
    draft_pick_overall: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Guardian(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    phone: str
    volunteer_hours_logged: float
    volunteer_status: str
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    background_check_passed: bool
    created_at: str
    updated_at: str
    version: int


class Referee(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    certification_level: str
    weekly_assignment_cap: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    head_coach_id: str
    draft_position: int
    roster_count: int
    tier_a_count: int
    wins: int
    losses: int
    playoff_seed: Optional[int]
    playoff_status: str
    created_at: str
    updated_at: str
    version: int


class Game(TypedDict, total=False):
    id: str
    season_id: str
    home_team_id: str
    away_team_id: str
    game_type: str
    field_id: str
    scheduled_start: str
    scheduled_end: str
    original_scheduled_start: str
    referee_id: Optional[str]
    status: str
    home_score: Optional[int]
    away_score: Optional[int]
    bracket_round: Optional[int]
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict, total=False):
    id: str
    season_id: str
    guardian_id: str
    game_id: Optional[str]
    role: str
    scheduled_start: str
    scheduled_end: str
    hours_credited: float
    status: str
    created_at: str
    updated_at: str
    version: int


# ===========================================================================
# Append-only — PRD §3.8: AuditEvent carries only id + created_at.
# ===========================================================================
class AuditEvent(TypedDict, total=False):
    id: str
    entity_type: str
    entity_id: str
    actor_role: str
    actor_id: str
    action: str
    details: dict
    created_at: str


__all__ = [
    "UserRole",
    "SeasonStatus",
    "AgeDivision",
    "PlayerStatus",
    "EvaluationTier",
    "VolunteerStatus",
    "GameStatus",
    "GameType",
    "PlayoffStatus",
    "CertificationLevel",
    "VolunteerShiftStatus",
    "VolunteerRole",
    "PostponeReason",
    "Season",
    "Player",
    "Guardian",
    "Coach",
    "Referee",
    "Team",
    "Game",
    "VolunteerShift",
    "AuditEvent",
]
