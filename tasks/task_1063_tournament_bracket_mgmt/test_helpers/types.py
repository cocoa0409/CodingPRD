"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted resource carries id/created_at/updated_at/version (PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    DIRECTOR = "Director"
    REFEREE = "Referee"
    PLAYER = "Player"
    PUBLIC = "Public"


class TournamentStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    BRACKET_READY = "BRACKET_READY"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RegistrationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    WITHDRAWN = "WITHDRAWN"
    ELIMINATED = "ELIMINATED"
    CHAMPION = "CHAMPION"


class MatchStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    VOIDED = "VOIDED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    VOID = "VOID"


class PayoutVariant(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StreamAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class TournamentFormat(str, Enum):
    SINGLE_ELIM = "SINGLE_ELIM"
    DOUBLE_ELIM = "DOUBLE_ELIM"
    ROUND_ROBIN = "ROUND_ROBIN"
    SWISS = "SWISS"


class SeedingMethod(str, Enum):
    RATING = "RATING"
    RANDOM_STABLE = "RANDOM_STABLE"
    MANUAL = "MANUAL"


class TiebreakMethod(str, Enum):
    SEED = "SEED"
    GAME_DIFF = "GAME_DIFF"


class Venue(TypedDict):
    id: str
    name: str
    address: str
    open_minute: int
    close_minute: int
    created_at: str
    updated_at: str
    version: int


class Station(TypedDict):
    id: str
    venue_id: str
    label: str
    created_at: str
    updated_at: str
    version: int


class StreamChannel(TypedDict):
    id: str
    name: str
    platform: str
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    display_name: str
    email: str
    rating: int
    tax_id_provided: bool
    created_at: str
    updated_at: str
    version: int


class Tournament(TypedDict):
    id: str
    name: str
    venue_id: str
    format: str
    status: str
    max_participants: int
    seeding_method: str
    tiebreak_method: str
    swiss_rounds: int
    num_swiss_rounds_played: int
    prize_pool_cents: int
    paid_places: int
    payout_variant: str
    unallocated_prize_cents: int
    registered_count: int
    checked_in_count: int
    alive_count: int
    eliminated_count: int
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    tournament_id: str
    player_id: str
    status: str
    seed: Optional[int]
    seed_input: Optional[int]
    checked_in_at: Optional[str]
    eliminated: bool
    final_placement: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict):
    id: str
    tournament_id: str
    bracket: str
    round_number: int
    slot_index: int
    home_registration_id: Optional[str]
    away_registration_id: Optional[str]
    home_score: int
    away_score: int
    winner_registration_id: Optional[str]
    loser_registration_id: Optional[str]
    next_match_id: Optional[str]
    loser_next_match_id: Optional[str]
    status: str
    station_id: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    reported_by_user_id: Optional[str]
    confirmed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StreamAssignment(TypedDict):
    id: str
    match_id: str
    channel_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    tournament_id: str
    registration_id: Optional[str]
    placement: int
    variant: str
    gross_amount_cents: int
    tax_withheld_cents: int
    net_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    match_id: str
    raised_by_registration_id: str
    reason: str
    status: str
    resolution_note: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
