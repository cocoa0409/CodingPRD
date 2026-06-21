"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class SeasonPhase(str, Enum):
    SETUP = "SETUP"
    REGULAR = "REGULAR"
    PLAYOFFS = "PLAYOFFS"
    COMPLETE = "COMPLETE"


class TradeWindowState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class TeamPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"


class PlayerStatus(str, Enum):
    FREE_AGENT = "FREE_AGENT"
    SIGNED = "SIGNED"


class ContractType(str, Enum):
    STANDARD = "STANDARD"
    TWO_WAY = "TWO_WAY"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WAIVED = "WAIVED"


class TradeStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class FineStatus(str, Enum):
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"


class SponsorshipStatus(str, Enum):
    PENDING = "PENDING"
    DISTRIBUTED = "DISTRIBUTED"


class UserRole(str, Enum):
    LEAGUE_COMMISSIONER = "LeagueCommissioner"
    TEAM_GM = "TeamGM"


# common_fields: true — id + created_at + updated_at + version
class Season(TypedDict):
    id: str
    name: str
    salary_cap_cents: int
    roster_min: int
    roster_max: int
    two_way_max: int
    penalty_threshold: int
    trade_window_state: str
    phase: str
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    season_id: str
    name: str
    market_size_weight: int
    payroll_active_cents: int
    penalty_points: int
    posture: str
    seed: Optional[int]
    eliminated: bool
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    season_id: str
    handle: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    team_id: str
    player_id: str
    base_salary_cents: int
    contract_type: str
    term_start: str
    term_end: str
    two_way_promoted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Stint(TypedDict):
    id: str
    contract_id: str
    player_id: str
    starts_at: str
    ends_at: str
    created_at: str
    updated_at: str
    version: int


class Trade(TypedDict):
    id: str
    season_id: str
    from_team_id: str
    to_team_id: str
    contract_ids_out: List[str]
    contract_ids_in: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Fine(TypedDict):
    id: str
    team_id: str
    player_id: str
    amount_cents: int
    penalty_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sponsorship(TypedDict):
    id: str
    season_id: str
    sponsor_name: str
    pool_cents: int
    league_share_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only audit record: id + created_at only.
class RevenueShare(TypedDict):
    id: str
    sponsorship_id: str
    team_id: str
    amount_cents: int
    weight_used: int
    created_at: str
