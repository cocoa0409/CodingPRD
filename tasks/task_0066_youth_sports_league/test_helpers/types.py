"""Domain types: entity TypedDicts, status enums, role enum (PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum (PRD §2.1) ───────────────────────────────


class UserRole(str, Enum):
    LEAGUE_ADMIN = "LeagueAdmin"
    COACH = "Coach"
    REFEREE = "Referee"
    PARENT_GUARDIAN = "ParentGuardian"


# ─── Status enums ───────────────────────────────────────


class LeagueStatus(str, Enum):
    SETUP = "SETUP"
    REGISTRATION = "REGISTRATION"
    EVALUATION = "EVALUATION"
    DRAFT = "DRAFT"
    SEASON = "SEASON"
    PLAYOFFS = "PLAYOFFS"
    CLOSED = "CLOSED"


class PlayerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    AGE_VERIFIED = "AGE_VERIFIED"
    EVALUATED = "EVALUATED"
    DRAFTED = "DRAFTED"
    ROSTERED = "ROSTERED"
    WITHDRAWN = "WITHDRAWN"


class PlayerTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class DraftPickStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class GameStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINAL = "FINAL"
    RAINED_OUT = "RAINED_OUT"
    FORFEITED = "FORFEITED"


class GameType(str, Enum):
    REGULAR = "REGULAR"
    PLAYOFF = "PLAYOFF"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"


class AssignmentRole(str, Enum):
    PLATE = "PLATE"
    BASE = "BASE"


class VolunteerCommitmentStatus(str, Enum):
    PLEDGED = "PLEDGED"
    FULFILLED = "FULFILLED"
    NO_SHOW = "NO_SHOW"


class VolunteerRole(str, Enum):
    SCOREKEEPER = "SCOREKEEPER"
    CONCESSIONS = "CONCESSIONS"
    FIELD_PREP = "FIELD_PREP"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ──


class League(TypedDict):
    id: str
    name: str
    season_year: int
    age_cutoff_date: str
    registration_open_iso: str
    registration_close_iso: str
    draft_snake: bool
    status: str
    total_registered_players: int
    draft_round_index: int
    created_at: str
    updated_at: str
    version: int


class Division(TypedDict):
    id: str
    league_id: str
    name: str
    min_league_age: int
    max_league_age: int
    roster_cap: int
    created_at: str
    updated_at: str
    version: int


class Family(TypedDict):
    id: str
    league_id: str
    guardian_email: str
    guardian_name: str
    volunteer_deposit_cents: int
    volunteer_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    league_id: str
    family_id: str
    division_id: str
    full_name: str
    birth_date: str
    league_age: int
    birth_certificate_ref: Optional[str]
    eval_speed: Optional[int]
    eval_hitting: Optional[int]
    eval_fielding: Optional[int]
    eval_score: Optional[float]
    tier: Optional[str]
    team_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    division_id: str
    league_id: str
    name: str
    coach_user_id: str
    draft_slot: int
    roster_count: int
    wins: int
    losses: int
    run_differential: int
    seed: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DraftPick(TypedDict):
    id: str
    league_id: str
    team_id: str
    player_id: str
    round_number: int
    overall_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict):
    id: str
    league_id: str
    name: str
    turnover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Referee(TypedDict):
    id: str
    league_id: str
    user_id: str
    full_name: str
    max_games_per_day: int
    created_at: str
    updated_at: str
    version: int


class Game(TypedDict):
    id: str
    league_id: str
    division_id: str
    home_team_id: str
    away_team_id: str
    field_id: str
    start_iso: str
    end_iso: str
    game_type: str
    playoff_round: Optional[int]
    home_runs: Optional[int]
    away_runs: Optional[int]
    winner_team_id: Optional[str]
    rainout_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RefereeAssignment(TypedDict):
    id: str
    game_id: str
    referee_id: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VolunteerCommitment(TypedDict):
    id: str
    game_id: str
    family_id: str
    role: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
