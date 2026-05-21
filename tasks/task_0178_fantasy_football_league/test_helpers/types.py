"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: primary persisted entities (League, Team, Player, RosterSlot,
WaiverClaim, TradeProposal, MatchupWeek, KeeperDesignation) carry id +
created_at + updated_at + version. The two immutable-with-respect-to-
update entities (DraftPick, TradeVote) carry only id + created_at.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    COMMISSIONER = "Commissioner"
    MANAGER = "Manager"


# ---------------------------------------------------------------------------
# League status (PRD §3.1, §3.3, §3.8)
# ---------------------------------------------------------------------------
class LeagueStatus(str, Enum):
    DRAFT_PENDING = "DRAFT_PENDING"
    DRAFTING = "DRAFTING"
    REGULAR_SEASON = "REGULAR_SEASON"
    PLAYOFFS = "PLAYOFFS"
    COMPLETED = "COMPLETED"
    ARCHIVED = "ARCHIVED"


class DraftMode(str, Enum):
    SNAKE = "SNAKE"
    AUCTION = "AUCTION"


class ScoringMode(str, Enum):
    STANDARD = "STANDARD"
    HALF_PPR = "HALF_PPR"
    PPR = "PPR"


class KeeperMode(str, Enum):
    NONE = "NONE"
    REDRAFT = "REDRAFT"
    DYNASTY = "DYNASTY"


# ---------------------------------------------------------------------------
# Player status (PRD §3.1, §3.5)
# ---------------------------------------------------------------------------
class PlayerStatusTag(str, Enum):
    ACTIVE = "ACTIVE"
    QUESTIONABLE = "QUESTIONABLE"
    OUT = "OUT"
    IR_ELIGIBLE = "IR_ELIGIBLE"


class PlayerPosition(str, Enum):
    QB = "QB"
    RB = "RB"
    WR = "WR"
    TE = "TE"
    K = "K"
    DST = "DST"
    FLEX_RWT = "FLEX_RWT"


# ---------------------------------------------------------------------------
# RosterSlot (PRD §3.4)
# ---------------------------------------------------------------------------
class SlotType(str, Enum):
    STARTER = "STARTER"
    BENCH = "BENCH"
    IR = "IR"


# ---------------------------------------------------------------------------
# Waiver claim status (PRD §3.6)
# ---------------------------------------------------------------------------
class WaiverClaimStatus(str, Enum):
    PENDING = "PENDING"
    AWARDED = "AWARDED"
    LOST = "LOST"
    CANCELED = "CANCELED"


# ---------------------------------------------------------------------------
# Trade status (PRD §3.7)
# ---------------------------------------------------------------------------
class TradeStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED_PENDING_REVIEW = "ACCEPTED_PENDING_REVIEW"
    VETOED = "VETOED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CANCELED = "CANCELED"


class TradeVoteValue(str, Enum):
    VETO = "VETO"
    APPROVE = "APPROVE"


# ---------------------------------------------------------------------------
# Matchup status (PRD §3.5)
# ---------------------------------------------------------------------------
class MatchupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LOCKED = "LOCKED"
    SCORED = "SCORED"


# ---------------------------------------------------------------------------
# Keeper status (PRD §3.2)
# ---------------------------------------------------------------------------
class KeeperStatus(str, Enum):
    DECLARED = "DECLARED"
    LOCKED = "LOCKED"
    CONVERTED = "CONVERTED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 + §3.x)
# ---------------------------------------------------------------------------
class League(TypedDict, total=False):
    id: str
    name: str
    season_year: int
    draft_mode: str
    scoring_mode: str
    team_count: int
    roster_size: int
    starter_count: int
    ir_slots: int
    faab_budget_dollars: int
    auction_budget_dollars: int
    keeper_mode: str
    keeper_cap: int
    veto_quorum_pct: int
    trade_review_hours: int
    waiver_period_hours: int
    playoff_team_count: int
    regular_season_weeks: int
    status: str
    current_week: int
    now_ts: str
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    league_id: str
    name: str
    manager_user_id: str
    draft_position: Optional[int]
    faab_balance_dollars: int
    auction_balance_dollars: int
    wins: int
    losses: int
    points_for: float
    standing_seed: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict, total=False):
    id: str
    full_name: str
    nfl_team: str
    position: str
    status_tag: str
    weekly_proj_points: float
    created_at: str
    updated_at: str
    version: int


class DraftPick(TypedDict, total=False):
    """PRD §2.4: DraftPick carries ONLY id and created_at (no updated_at,
    no version)."""
    id: str
    league_id: str
    team_id: str
    player_id: str
    round_number: int
    overall_pick_index: int
    price_dollars: int
    is_keeper: bool
    created_at: str


class RosterSlot(TypedDict, total=False):
    id: str
    team_id: str
    player_id: str
    slot_type: str
    position_label: Optional[str]
    locked_until_ts: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaiverClaim(TypedDict, total=False):
    id: str
    league_id: str
    team_id: str
    add_player_id: str
    drop_player_id: Optional[str]
    bid_dollars: int
    priority_seed: int
    status: str
    settle_ts: str
    created_at: str
    updated_at: str
    version: int


class TradeProposal(TypedDict, total=False):
    id: str
    league_id: str
    proposing_team_id: str
    counterparty_team_id: str
    send_player_ids: List[str]
    receive_player_ids: List[str]
    send_faab_dollars: int
    receive_faab_dollars: int
    status: str
    review_deadline_ts: Optional[str]
    veto_count: int
    created_at: str
    updated_at: str
    version: int


class TradeVote(TypedDict, total=False):
    """PRD §2.4 / §3.7: TradeVote carries ONLY id, trade_proposal_id,
    voting_team_id, vote, and cast_at_ts (no updated_at, no version)."""
    id: str
    trade_proposal_id: str
    voting_team_id: str
    vote: str
    cast_at_ts: str
    created_at: str


class MatchupWeek(TypedDict, total=False):
    id: str
    league_id: str
    week_number: int
    home_team_id: str
    away_team_id: str
    home_points: float
    away_points: float
    status: str
    is_playoff: bool
    bracket_round: Optional[int]
    created_at: str
    updated_at: str
    version: int


class KeeperDesignation(TypedDict, total=False):
    id: str
    league_id: str
    team_id: str
    player_id: str
    season_year: int
    assigned_round: Optional[int]
    assigned_price_dollars: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


__all__ = [
    "UserRole",
    "LeagueStatus",
    "DraftMode",
    "ScoringMode",
    "KeeperMode",
    "PlayerStatusTag",
    "PlayerPosition",
    "SlotType",
    "WaiverClaimStatus",
    "TradeStatus",
    "TradeVoteValue",
    "MatchupStatus",
    "KeeperStatus",
    "League",
    "Team",
    "Player",
    "DraftPick",
    "RosterSlot",
    "WaiverClaim",
    "TradeProposal",
    "TradeVote",
    "MatchupWeek",
    "KeeperDesignation",
]
