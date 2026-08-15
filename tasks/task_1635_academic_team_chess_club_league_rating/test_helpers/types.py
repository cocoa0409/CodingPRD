"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class SeasonStatus(str, Enum):
    REGISTRATION = "REGISTRATION"
    ACTIVE = "ACTIVE"
    FINALIZING = "FINALIZING"
    COMPLETED = "COMPLETED"


class ClubStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    DELINQUENT = "DELINQUENT"
    SUSPENDED = "SUSPENDED"


class CoachStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class CertificationLevel(str, Enum):
    CLUB = "CLUB"
    CERTIFIED = "CERTIFIED"
    SENIOR = "SENIOR"


class PlayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    SUSPENDED = "SUSPENDED"
    GRADUATED = "GRADUATED"


class MembershipStatus(str, Enum):
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    REFUNDED = "REFUNDED"


class LedgerEntryType(str, Enum):
    MEMBERSHIP_DUE = "MEMBERSHIP_DUE"
    ENTRY_FEE = "ENTRY_FEE"
    ENTRY_REFUND = "ENTRY_REFUND"
    TRAVEL_STIPEND = "TRAVEL_STIPEND"
    ADJUSTMENT = "ADJUSTMENT"
    REVERSAL = "REVERSAL"


class MeetStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    PAIRINGS_PUBLISHED = "PAIRINGS_PUBLISHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"


class PairingResult(str, Enum):
    UNREPORTED = "UNREPORTED"
    WHITE_WIN = "WHITE_WIN"
    BLACK_WIN = "BLACK_WIN"
    DRAW = "DRAW"
    WHITE_FORFEIT_WIN = "WHITE_FORFEIT_WIN"
    BLACK_FORFEIT_WIN = "BLACK_FORFEIT_WIN"
    DOUBLE_FORFEIT = "DOUBLE_FORFEIT"


class PairingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    REPORTED = "REPORTED"
    CONFIRMED = "CONFIRMED"
    DISPUTED = "DISPUTED"
    REPLACED = "REPLACED"
    CANCELLED = "CANCELLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"
    WITHDRAWN = "WITHDRAWN"


class TournamentStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SectionStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class EntryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    FINISHED = "FINISHED"
    WITHDRAWN = "WITHDRAWN"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class EventType(str, Enum):
    MEET = "MEET"
    TOURNAMENT = "TOURNAMENT"


class BidType(str, Enum):
    INDIVIDUAL_STATE = "INDIVIDUAL_STATE"
    TEAM_STATE = "TEAM_STATE"
    NATIONAL = "NATIONAL"


class BidStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class FormulaVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ESTABLISHED = "ESTABLISHED"


class RatingEventStatus(str, Enum):
    EFFECTIVE = "EFFECTIVE"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    FEDERATION_ADMIN = "FederationAdmin"
    CLUB_COACH = "ClubCoach"
    PROCTOR = "Proctor"
    TREASURER = "Treasurer"
    AUDITOR = "Auditor"


# ─── Entity TypedDicts ────────────────────────────────
# Primary resources carry id + created_at + updated_at + version (PRD §2.4).
# LedgerEntry and RatingEvent are immutable event rows: only id + created_at.


class Season(TypedDict, total=False):
    id: str
    name: str
    start_date: str
    end_date: str
    dues_deadline: str
    regular_due_cents: int
    late_due_cents: int
    provisional_game_threshold: int
    base_rating: int
    state_bid_slots_per_region: int
    travel_base_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Club(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    school_name: str
    region_code: str
    travel_tier: int
    account_balance_cents: int
    projected_travel_stipend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Coach(TypedDict, total=False):
    id: str
    club_id: str
    full_name: str
    email: str
    certification_level: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict, total=False):
    id: str
    club_id: str
    full_name: str
    grade_level: int
    initial_rating: int
    initial_rated_games: int
    rating: int
    peak_rating: int
    rated_games_played: int
    is_provisional: bool
    performance_points: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict, total=False):
    id: str
    player_id: str
    season_id: str
    fee_cents: int
    paid_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    # Immutable event row: only id + created_at system fields (PRD §2.4).
    id: str
    club_id: str
    entry_type: str
    amount_cents: int
    memo: Optional[str]
    posted_by_user_id: str
    membership_id: Optional[str]
    entry_id: Optional[str]
    reversal_of_id: Optional[str]
    reversed_by_id: Optional[str]
    created_at: str


class Meet(TypedDict, total=False):
    id: str
    season_id: str
    host_club_id: str
    away_club_id: str
    scheduled_date: str
    rounds_count: int
    boards_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pairing(TypedDict, total=False):
    id: str
    meet_id: str
    round_number: int
    board_number: int
    white_player_id: str
    black_player_id: str
    result: str
    reported_by_coach_id: Optional[str]
    was_confirmed: bool
    confirmed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    pairing_id: str
    raised_by_coach_id: str
    reason: str
    resolved_result: Optional[str]
    resolution_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Tournament(TypedDict, total=False):
    id: str
    season_id: str
    host_club_id: Optional[str]
    name: str
    start_date: str
    end_date: str
    entry_fee_cents: int
    early_bird_deadline: Optional[str]
    early_bird_discount_pct: Optional[float]
    capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TournamentSection(TypedDict, total=False):
    id: str
    tournament_id: str
    name: str
    min_rating: int
    max_rating: int
    allow_provisional: bool
    max_entries: int
    current_entries: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TournamentEntry(TypedDict, total=False):
    id: str
    section_id: str
    player_id: str
    fee_cents: int
    refund_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProctorAssignment(TypedDict, total=False):
    id: str
    coach_id: str
    event_type: str
    meet_id: Optional[str]
    tournament_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualificationBid(TypedDict, total=False):
    id: str
    season_id: str
    club_id: str
    player_id: Optional[str]
    bid_type: str
    offer_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RatingEvent(TypedDict, total=False):
    # Immutable event row: only id + created_at system fields (PRD §2.4).
    id: str
    player_id: str
    pairing_id: str
    season_id: str
    formula_variant: str
    opponent_rating_snapshot: int
    score: float
    k_factor: Optional[int]
    rating_before: int
    rating_after: int
    confirmed_at: str
    status: str
    created_at: str


class StandingSnapshot(TypedDict, total=False):
    id: str
    season_id: str
    club_id: str
    match_points: float
    game_points: float
    sonneborn_berger: float
    forfeit_losses: int
    rank: int
    is_final: bool
    created_at: str
    updated_at: str
    version: int


class TravelStipend(TypedDict, total=False):
    id: str
    season_id: str
    club_id: str
    meets_counted: int
    amount_cents: int
    ledger_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
