"""Domain types: entity shapes, status enums, role enum (PRD field names)."""
from enum import Enum
from typing import Dict, Optional, TypedDict


class TournamentStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_LOCKED = "REGISTRATION_LOCKED"
    PRELIMS_ACTIVE = "PRELIMS_ACTIVE"
    ELIMS_ACTIVE = "ELIMS_ACTIVE"
    COMPLETED = "COMPLETED"


class ResultsVisibility(str, Enum):
    HIDDEN = "HIDDEN"
    PUBLISHED = "PUBLISHED"
    CERTIFIED = "CERTIFIED"


class SchoolStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CONFIRMED = "CONFIRMED"


class ObligationStatus(str, Enum):
    SATISFIED = "SATISFIED"
    DEFICIENT = "DEFICIENT"


class EventType(str, Enum):
    DEBATE = "DEBATE"
    SPEECH = "SPEECH"


class DivisionLevel(str, Enum):
    VARSITY = "VARSITY"
    JV = "JV"
    NOVICE = "NOVICE"


class EntryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"
    COMPETING = "COMPETING"
    ADVANCED = "ADVANCED"
    ELIMINATED = "ELIMINATED"
    FINISHED = "FINISHED"


class FinalPlacement(str, Enum):
    CHAMPION = "CHAMPION"
    RUNNER_UP = "RUNNER_UP"
    SEMIFINALIST = "SEMIFINALIST"
    QUARTERFINALIST = "QUARTERFINALIST"
    OCTOFINALIST = "OCTOFINALIST"
    NON_BREAKING = "NON_BREAKING"


class JudgeType(str, Enum):
    SCHOOL_PROVIDED = "SCHOOL_PROVIDED"
    HIRED = "HIRED"


class JudgeStatus(str, Enum):
    REGISTERED = "REGISTERED"
    COMMITTED = "COMMITTED"
    WITHDRAWN = "WITHDRAWN"


class RoundKind(str, Enum):
    PRELIM = "PRELIM"
    ELIM = "ELIM"


class RoundStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAIRED = "PAIRED"
    BALLOTS_OPEN = "BALLOTS_OPEN"
    TABULATED = "TABULATED"


class PairingFormat(str, Enum):
    HEAD_TO_HEAD = "HEAD_TO_HEAD"
    SECTION = "SECTION"


class PairingStatus(str, Enum):
    PENDING_STAFFING = "PENDING_STAFFING"
    STAFFED = "STAFFED"
    BALLOT_RELEASED = "BALLOT_RELEASED"
    BALLOT_SUBMITTED = "BALLOT_SUBMITTED"
    VERIFIED = "VERIFIED"


class PairingSide(str, Enum):
    AFF = "AFF"
    NEG = "NEG"
    SPEAKER = "SPEAKER"


class BallotStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    VOIDED = "VOIDED"


class ContractStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FILLED = "FILLED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class OrderKind(str, Enum):
    CATERING = "CATERING"
    AWARDS = "AWARDS"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    FULFILLED = "FULFILLED"


class UserRole(str, Enum):
    TOURNAMENT_DIRECTOR = "TournamentDirector"
    TAB_STAFF = "TabStaff"
    SCHOOL_COACH = "SchoolCoach"
    JUDGE = "Judge"


class Tournament(TypedDict, total=False):
    id: str
    name: str
    status: str
    results_visibility: str
    registration_opens_at: str
    registration_locks_at: str
    prelim_round_count: int
    entry_fee_cents: int
    tournament_staff_count: int
    late_fee_starts_at: Optional[str]
    late_fee_surcharge_pct: float
    created_at: str
    updated_at: str
    version: int


class School(TypedDict, total=False):
    id: str
    tournament_id: str
    name: str
    status: str
    credit_limit_cents: Optional[int]
    confirmed_entry_count: int
    judge_obligation_rounds: int
    covered_judge_rounds: int
    shortfall_rounds: int
    obligation_status: str
    invoice_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class EventDivision(TypedDict, total=False):
    id: str
    tournament_id: str
    event_type: str
    event_code: str
    division: str
    per_school_entry_cap: int
    global_entry_cap: int
    competing_entry_count: int
    bracket_size: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Entry(TypedDict, total=False):
    id: str
    school_id: str
    division_id: str
    competitor_name: str
    status: str
    wins: int
    losses: int
    speaker_points_raw: int
    speaker_points_adjusted: int
    rank_points_raw: int
    rank_points_adjusted: int
    opponent_strength: int
    prelim_rank: Optional[int]
    has_received_bye: bool
    seed: Optional[int]
    final_placement: Optional[str]
    qualification_points: Optional[int]
    fee_charged_cents: int
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict, total=False):
    id: str
    tournament_id: str
    school_id: Optional[str]
    name: str
    judge_type: str
    status: str
    commitment_rounds: int
    assigned_round_count: int
    created_at: str
    updated_at: str
    version: int


class JudgeConflict(TypedDict, total=False):
    """Carries only id + created_at (no updated_at, no version) per PRD §2.4."""
    id: str
    judge_id: str
    school_id: str
    reason: Optional[str]
    created_at: str


class Room(TypedDict, total=False):
    id: str
    tournament_id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Round(TypedDict, total=False):
    id: str
    division_id: str
    round_number: int
    kind: str
    starts_at: str
    ends_at: str
    status: str
    pairings_total: int
    pairings_verified_count: int
    created_at: str
    updated_at: str
    version: int


class Pairing(TypedDict, total=False):
    id: str
    round_id: str
    format: str
    room_id: Optional[str]
    judge_id: Optional[str]
    status: str
    is_bye: bool
    winner_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PairingEntry(TypedDict, total=False):
    """Carries only id + created_at (no updated_at, no version) per PRD §2.4."""
    id: str
    pairing_id: str
    entry_id: str
    side: str
    draw_position: int
    created_at: str


class Ballot(TypedDict, total=False):
    id: str
    pairing_id: str
    judge_id: str
    status: str
    winner_entry_id: Optional[str]
    speaker_points: Optional[Dict[str, int]]
    ranks: Optional[Dict[str, int]]
    allow_low_point_win: bool
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HiredJudgeContract(TypedDict, total=False):
    id: str
    school_id: str
    status: str
    rounds_requested: int
    rounds_released: int
    rounds_active: int
    hired_judge_id: Optional[str]
    fee_quote_cents: int
    final_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LogisticsOrder(TypedDict, total=False):
    id: str
    tournament_id: str
    kind: str
    status: str
    headcount_demand: int
    meal_count: int
    awards_count: int
    frozen_meal_count: Optional[int]
    frozen_awards_count: Optional[int]
    created_at: str
    updated_at: str
    version: int
