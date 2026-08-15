"""Domain types: entity TypedDicts, status enums, role enum (PRD §3, §4)."""
from enum import Enum
from typing import List, Optional, TypedDict


class TournamentStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    REGISTRATION_LOCKED = "REGISTRATION_LOCKED"
    SEEDED = "SEEDED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PAYOUTS_FINALIZED = "PAYOUTS_FINALIZED"
    CANCELLED = "CANCELLED"


class PlayerEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    APPEALED = "APPEALED"
    LOCKED = "LOCKED"
    FORFEITED = "FORFEITED"


class RosterSlotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"
    INELIGIBLE = "INELIGIBLE"


class SlotRole(str, Enum):
    STARTER = "STARTER"
    SUBSTITUTE = "SUBSTITUTE"


class ServerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


class MatchStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    LOBBY_OPEN = "LOBBY_OPEN"
    LIVE = "LIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    UNDER_DISPUTE = "UNDER_DISPUTE"
    CONFIRMED = "CONFIRMED"
    OVERTURNED = "OVERTURNED"
    FORFEIT = "FORFEIT"
    CANCELLED = "CANCELLED"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED_UPHELD = "CLOSED_UPHELD"
    CLOSED_OVERTURNED = "CLOSED_OVERTURNED"
    APPEALED = "APPEALED"


class DisputeReason(str, Enum):
    RULE_VIOLATION = "RULE_VIOLATION"
    SCORE_DISCREPANCY = "SCORE_DISCREPANCY"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"
    CONDUCT = "CONDUCT"


class DisputeRuling(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class DisputeRemedy(str, Enum):
    WINNER_FLIP = "WINNER_FLIP"
    REMATCH = "REMATCH"


class IntegrityCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED_CLEARED = "RESOLVED_CLEARED"
    RESOLVED_VIOLATION = "RESOLVED_VIOLATION"


class TalentBookingStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class PayoutComputeMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PayoutDocStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PayoutDocType(str, Enum):
    W9 = "W9"
    W8BEN = "W8BEN"
    GUARDIAN_W9 = "GUARDIAN_W9"


class PayoutDisbursementStatus(str, Enum):
    COMPUTED = "COMPUTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOID = "VOID"


class SponsorDealStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONTRACTED = "CONTRACTED"
    ACTIVATED = "ACTIVATED"
    VOID = "VOID"


class Region(str, Enum):
    NA = "NA"
    EU = "EU"
    APAC = "APAC"
    LATAM = "LATAM"


class UserRole(str, Enum):
    ORGANIZER_ADMIN = "OrganizerAdmin"
    TOURNAMENT_DIRECTOR = "TournamentDirector"
    TEAM_MANAGER = "TeamManager"
    PLAYER = "Player"
    REFEREE = "Referee"
    ANTI_CHEAT_INVESTIGATOR = "AntiCheatInvestigator"
    BROADCAST_PRODUCER = "BroadcastProducer"
    PAYOUT_OFFICER = "PayoutOfficer"
    SPONSOR_MANAGER = "SponsorManager"


# All entities below carry the common resource properties of PRD §2.4:
# id, created_at, updated_at, version.


class Tournament(TypedDict):
    id: str
    name: str
    game_title: str
    region: str
    prize_pool_target_cents: int
    funded_pool_cents: int
    roster_size: int
    max_roster_size: int
    registration_opens_at: str
    registration_closes_at: str
    minor_curfew_local: str
    status: str
    bracket_version: int
    placements_assigned: bool
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    handle: str
    date_of_birth: str
    region: str
    eligibility_status: str
    ac_strike_events: List[dict]
    active_strike_count: int
    created_at: str
    updated_at: str
    version: int


class Registration(TypedDict):
    id: str
    tournament_id: str
    team_name: str
    manager_contact_email: str
    region_rank_points: int
    prior_event_points: int
    qualifier_wins: int
    captain_player_id: str
    status: str
    appeal_used: bool
    seed_score: Optional[float]
    seed_position: Optional[int]
    placement: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RosterSlot(TypedDict):
    id: str
    registration_id: str
    player_id: str
    slot_role: str
    status: str
    age_at_lock_years: Optional[int]
    is_minor: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class ServerInstance(TypedDict):
    id: str
    tournament_id: str
    label: str
    region: str
    status: str
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict):
    id: str
    tournament_id: str
    bracket_round: int
    bracket_slot: int
    next_match_id: Optional[str]
    home_registration_id: Optional[str]
    away_registration_id: Optional[str]
    winner_registration_id: Optional[str]
    server_id: Optional[str]
    scheduled_start_at: Optional[str]
    duration_minutes: Optional[int]
    status: str
    home_score: Optional[int]
    away_score: Optional[int]
    assigned_referee_id: Optional[str]
    reported_by_user_id: Optional[str]
    confirmed_by_user_id: Optional[str]
    tactical_pauses_home: int
    tactical_pauses_away: int
    completed_at: Optional[str]
    dispute_window_closes_at: Optional[str]
    forfeiting_registration_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    match_id: str
    registration_id: str
    reason: str
    details: str
    status: str
    appeal_used: bool
    ruling: Optional[str]
    remedy: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IntegrityCase(TypedDict):
    id: str
    player_id: str
    match_id: Optional[str]
    evidence_summary: str
    status: str
    opened_by_user_id: str
    resolved_by_user_id: Optional[str]
    strike_issued: bool
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Talent(TypedDict):
    id: str
    stage_name: str
    home_region: str
    day_rate_cents: int
    cross_region: bool
    created_at: str
    updated_at: str
    version: int


class TalentBooking(TypedDict):
    id: str
    tournament_id: str
    talent_id: str
    stage_label: str
    shift_start_at: str
    shift_end_at: str
    status: str
    fee_quote_cents: int
    fee_final_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PayoutRecord(TypedDict):
    id: str
    tournament_id: str
    registration_id: str
    payee_player_id: str
    placement: int
    compute_run_mode: str
    bracket_version: int
    gross_amount_cents: int
    withholding_cents: int
    net_amount_cents: int
    payee_is_minor: bool
    guardian_name: Optional[str]
    guardian_email: Optional[str]
    doc_status: str
    doc_type: Optional[str]
    doc_verified_by_user_id: Optional[str]
    disbursement_status: str
    approved_by_user_id: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SponsorDeal(TypedDict):
    id: str
    tournament_id: str
    sponsor_name: str
    contact_user_id: str
    rights_tier: str
    bonus_cents: int
    content_rights: List[str]
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
