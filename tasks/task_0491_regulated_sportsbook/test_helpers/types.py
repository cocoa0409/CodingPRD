"""Domain types: entity TypedDicts, status enums, role enum.

Field presence follows the PRD: Account, RGControl, Event, Market, Selection,
Bet, Promotion, and BonusGrant carry id/created_at/updated_at/version; GeoCheck,
BetLeg, and LedgerEntry are append-only and carry only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Roles ---
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    BETTOR = "Bettor"
    TRADING_OPS = "TradingOps"
    SETTLEMENT_AGENT = "SettlementAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


# --- Status enums ---
class KycStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class RgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COOLING_OFF = "COOLING_OFF"
    SELF_EXCLUDED = "SELF_EXCLUDED"


class RGControlType(str, Enum):
    DEPOSIT_LIMIT = "DEPOSIT_LIMIT"
    WAGER_LIMIT = "WAGER_LIMIT"
    NET_LOSS_LIMIT = "NET_LOSS_LIMIT"
    COOLING_OFF = "COOLING_OFF"
    SELF_EXCLUSION = "SELF_EXCLUSION"


class RGControlStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class EventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class MarketStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class SelectionResult(str, Enum):
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"
    PUSH = "PUSH"
    VOID = "VOID"


class BetType(str, Enum):
    SINGLE = "SINGLE"
    PARLAY = "PARLAY"
    SAME_GAME_PARLAY = "SAME_GAME_PARLAY"


class BetStatus(str, Enum):
    PLACED = "PLACED"
    WON = "WON"
    LOST = "LOST"
    PUSHED = "PUSHED"
    VOIDED = "VOIDED"
    CASHED_OUT = "CASHED_OUT"


class StakeBucket(str, Enum):
    CASH = "CASH"
    BONUS = "BONUS"


class LegResult(str, Enum):
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"
    PUSH = "PUSH"
    VOID = "VOID"


class PromotionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    ENDED = "ENDED"


class BonusGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    FORFEITED = "FORFEITED"


class LedgerEntryType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    STAKE = "STAKE"
    PAYOUT = "PAYOUT"
    BONUS_GRANT = "BONUS_GRANT"
    CASHOUT = "CASHOUT"
    VOID_REFUND = "VOID_REFUND"


class LedgerBucket(str, Enum):
    CASH = "CASH"
    BONUS = "BONUS"


class LedgerRefType(str, Enum):
    BET = "BET"
    BONUS_GRANT = "BONUS_GRANT"
    NONE = "NONE"


# --- Entity TypedDicts (common_fields: true → id/created_at/updated_at/version) ---
class Account(TypedDict):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    residence_state: str
    kyc_status: str
    rg_status: str
    cash_balance_cents: int
    bonus_balance_cents: int
    lifetime_deposits_cents: int
    cooling_off_until: Optional[str]
    kyc_decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RGControl(TypedDict):
    id: str
    account_id: str
    control_type: str
    period: str
    limit_cents: Optional[int]
    duration_days: Optional[int]
    status: str
    set_at: str
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    sport: str
    home_team: str
    away_team: str
    starts_at: str
    status: str
    home_score: Optional[int]
    away_score: Optional[int]
    result_posted_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Market(TypedDict):
    id: str
    event_id: str
    market_type: str
    line: Optional[float]
    liability_cap_cents: int
    current_liability_cents: int
    status: str
    set_by: str
    created_at: str
    updated_at: str
    version: int


class Selection(TypedDict):
    id: str
    market_id: str
    name: str
    american_odds: int
    result: str
    created_at: str
    updated_at: str
    version: int


class Bet(TypedDict):
    id: str
    account_id: str
    bet_type: str
    stake_cents: int
    stake_bucket: str
    combined_decimal_odds: float
    potential_payout_cents: int
    actual_payout_cents: int
    bonus_grant_id: Optional[str]
    status: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    code: str
    bonus_cents: int
    wagering_multiplier: int
    min_odds_american: int
    max_claims: int
    claims_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BonusGrant(TypedDict):
    id: str
    account_id: str
    promotion_id: str
    bonus_cents: int
    wagering_target_cents: int
    wagering_progress_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities (common_fields: false → id/created_at only) ---
class GeoCheck(TypedDict):
    id: str
    account_id: str
    detected_state: str
    accuracy_meters: int
    is_vpn_suspected: bool
    eligible: bool
    expires_at: str
    created_at: str


class BetLeg(TypedDict):
    id: str
    bet_id: str
    selection_id: str
    odds_at_placement: int
    decimal_odds_at_placement: float
    leg_result: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    account_id: str
    entry_type: str
    bucket: str
    amount_cents: int
    ref_type: str
    ref_id: Optional[str]
    created_at: str
