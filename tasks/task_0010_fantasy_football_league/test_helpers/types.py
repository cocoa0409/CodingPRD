"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class LeagueStatus(str, Enum):
    SETUP = "SETUP"
    DRAFTING = "DRAFTING"
    IN_SEASON = "IN_SEASON"
    PLAYOFFS = "PLAYOFFS"
    COMPLETE = "COMPLETE"


class DraftType(str, Enum):
    SNAKE = "SNAKE"
    AUCTION = "AUCTION"


class TiebreakRule(str, Enum):
    STANDARD = "STANDARD"
    DIVISION_FIRST = "DIVISION_FIRST"


class PlayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INJURED = "INJURED"
    IR_PLACED = "IR_PLACED"
    RELEASED = "RELEASED"


class PlayerPosition(str, Enum):
    QB = "QB"
    RB = "RB"
    WR = "WR"
    TE = "TE"
    K = "K"
    DEF = "DEF"


class SlotType(str, Enum):
    STARTER = "STARTER"
    BENCH = "BENCH"
    IR = "IR"


class WaiverClaimState(str, Enum):
    SUBMITTED = "SUBMITTED"
    WON = "WON"
    LOST_BID = "LOST_BID"
    INVALID = "INVALID"
    CANCELLED = "CANCELLED"


class TradeState(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    PENDING_VETO = "PENDING_VETO"
    VETOED = "VETOED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class VetoVoteValue(str, Enum):
    VETO = "VETO"
    ALLOW = "ALLOW"


class MatchupType(str, Enum):
    REGULAR = "REGULAR"
    PLAYOFF = "PLAYOFF"


class MatchupState(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class UserRole(str, Enum):
    COMMISSIONER = "Commissioner"
    TEAM_OWNER = "TeamOwner"


# ─── Entity TypedDicts ────────────────────────────────────────────────────
# common_fields: true → id + created_at + updated_at + version
# common_fields: false → id + created_at only (VetoVote)

class League(TypedDict):
    id: str
    name: str
    draft_type: str
    roster_size: int
    starter_slot_count: int
    ir_slot_count: int
    faab_budget_cents: int
    veto_threshold: int
    keeper_limit: int
    playoff_team_count: int
    tiebreak_rule: str
    status: str
    current_week: int
    total_faab_pool_cents: int
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    league_id: str
    display_name: str
    division: str
    faab_balance_cents: int
    waiver_priority: int
    wins: int
    losses: int
    total_points_for: float
    total_points_against: float
    intra_division_wins: int
    playoff_seed: int
    keeper_player_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    full_name: str
    position: str
    nfl_team: str
    status: str
    projected_points: float
    replacement_value: float
    current_team_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DraftPick(TypedDict):
    id: str
    league_id: str
    team_id: str
    player_id: str
    round: int
    overall_pick: int
    cost_cents: int
    keeper_round: Optional[int]
    is_keeper: bool
    created_at: str
    updated_at: str
    version: int


class RosterSlot(TypedDict):
    id: str
    team_id: str
    player_id: str
    slot_type: str
    week_locked: int
    created_at: str
    updated_at: str
    version: int


class WaiverClaim(TypedDict):
    id: str
    league_id: str
    team_id: str
    player_id: str
    bid_cents: int
    drop_player_id: Optional[str]
    state: str
    processing_week: int
    priority_at_submission: int
    created_at: str
    updated_at: str
    version: int


class Trade(TypedDict):
    id: str
    league_id: str
    proposing_team_id: str
    target_team_id: str
    players_offered: List[str]
    players_requested: List[str]
    faab_offered_cents: int
    state: str
    veto_votes_count: int
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# VetoVote — common_fields: false (immutable audit record).
# Carries only id + created_at; no updated_at, no version.
class VetoVote(TypedDict):
    id: str
    trade_id: str
    voter_team_id: str
    vote: str
    created_at: str


class PlayoffMatchup(TypedDict):
    id: str
    league_id: str
    week: int
    matchup_type: str
    round: int
    home_team_id: str
    away_team_id: str
    home_score: float
    away_score: float
    state: str
    winner_team_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
