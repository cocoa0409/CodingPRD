"""Domain types for the Esports Tournament Management API.

Entity TypedDicts, status enums, and the role enum. Per PRD §2.4 only
Tournament, TeamRegistration, PlayerContract, Match, MatchIncident,
Referee, PrizePayout, TransferOffer, and TransferWindow carry the full
common-field set (id + created_at + updated_at + version). The four
append-only entities (IdentityVerification, DraftEvent,
CrowdfundContribution, AuditLogEntry) plus the Clock singleton carry
ONLY id + created_at — their TypedDicts deliberately omit updated_at
and version.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    LEAGUE_ADMIN = "LeagueAdmin"
    TEAM_MANAGER = "TeamManager"
    PLAYER = "Player"
    REFEREE = "Referee"


# ---------------------------------------------------------------------------
# Tournament-domain enums (PRD §3.1)
# ---------------------------------------------------------------------------
class TournamentFormat(str, Enum):
    SWISS = "SWISS"
    DOUBLE_ELIMINATION = "DOUBLE_ELIMINATION"
    ROUND_ROBIN = "ROUND_ROBIN"
    GROUP_PLAYOFFS = "GROUP_PLAYOFFS"


class TournamentRegion(str, Enum):
    NA = "NA"
    EU = "EU"
    APAC = "APAC"
    SA = "SA"
    GLOBAL = "GLOBAL"


class TournamentStatus(str, Enum):
    DRAFT = "DRAFT"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    ROSTER_LOCKED = "ROSTER_LOCKED"
    BRACKET_PUBLISHED = "BRACKET_PUBLISHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PRIZES_DISTRIBUTED = "PRIZES_DISTRIBUTED"
    CANCELLED = "CANCELLED"


class SeedingRule(str, Enum):
    RANKING = "RANKING"
    RANDOM = "RANDOM"
    REGIONAL_BALANCE = "REGIONAL_BALANCE"


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    KRW = "KRW"
    CNY = "CNY"


# ---------------------------------------------------------------------------
# Team-domain enums (PRD §3.2)
# ---------------------------------------------------------------------------
class TeamRegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    FEE_PENDING = "FEE_PENDING"
    REGISTERED = "REGISTERED"
    DISQUALIFIED = "DISQUALIFIED"
    WITHDRAWN = "WITHDRAWN"


class SponsorTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"


# ---------------------------------------------------------------------------
# PlayerContract-domain enums (PRD §3.3)
# ---------------------------------------------------------------------------
class ContractType(str, Enum):
    EXCLUSIVE = "EXCLUSIVE"
    LOAN = "LOAN"
    FREE_AGENT = "FREE_AGENT"


class RosterSlot(str, Enum):
    MAIN = "MAIN"
    SUBSTITUTE = "SUBSTITUTE"


class DisputeResolutionClause(str, Enum):
    ARBITRATION = "ARBITRATION"
    LITIGATION = "LITIGATION"
    MEDIATION = "MEDIATION"


class SignatoryParty(str, Enum):
    PLAYER = "PLAYER"
    TEAM_MANAGER = "TEAM_MANAGER"
    LEAGUE_ADMIN = "LEAGUE_ADMIN"


class PlayerContractStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURES = "PENDING_SIGNATURES"
    ACTIVE = "ACTIVE"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class IdentityVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Match-domain enums (PRD §3.4)
# ---------------------------------------------------------------------------
class MatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DRAFT_IN_PROGRESS = "DRAFT_IN_PROGRESS"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    FORFEITED = "FORFEITED"
    DISQUALIFIED = "DISQUALIFIED"


class DraftAction(str, Enum):
    BAN = "BAN"
    PICK = "PICK"


class DraftSide(str, Enum):
    A = "A"
    B = "B"


class DraftTargetType(str, Enum):
    MAP = "MAP"
    CHARACTER = "CHARACTER"


class DraftAnomalyType(str, Enum):
    DISCONNECT = "DISCONNECT"
    MISCLICK = "MISCLICK"


# ---------------------------------------------------------------------------
# Incident-domain enums (PRD §3.5)
# ---------------------------------------------------------------------------
class IncidentSubjectType(str, Enum):
    PLAYER = "PLAYER"
    TEAM = "TEAM"
    MATCH = "MATCH"


class IncidentClassification(str, Enum):
    LATENCY = "LATENCY"
    CHEATING_SUSPICION = "CHEATING_SUSPICION"
    UNSPORTSMANLIKE_CONDUCT = "UNSPORTSMANLIKE_CONDUCT"
    RULE_VIOLATION = "RULE_VIOLATION"


class IncidentEvidenceKind(str, Enum):
    REPLAY = "REPLAY"
    LOG = "LOG"
    SCREENSHOT = "SCREENSHOT"


class IncidentRuling(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    OVERTURNED = "OVERTURNED"


class IncidentPenaltyType(str, Enum):
    NONE = "NONE"
    WARNING = "WARNING"
    FORFEIT = "FORFEIT"
    DISQUALIFICATION = "DISQUALIFICATION"
    FINE = "FINE"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RULED = "RULED"
    APPEALED = "APPEALED"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Referee enums (PRD §3.4)
# ---------------------------------------------------------------------------
class RefereeCertificationLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class RefereeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# PrizePayout enums (PRD §3.6)
# ---------------------------------------------------------------------------
class PrizeAwardKind(str, Enum):
    PLACEMENT = "PLACEMENT"
    MVP = "MVP"
    SPECIAL_AWARD = "SPECIAL_AWARD"


class PrizePayoutStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"


# ---------------------------------------------------------------------------
# Crowdfund + Transfer enums (PRD §3.7)
# ---------------------------------------------------------------------------
class CrowdfundContributionStatus(str, Enum):
    PLEDGED = "PLEDGED"
    COLLECTED = "COLLECTED"
    REFUNDED = "REFUNDED"


class TransferOfferStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED_BY_FROM = "ACCEPTED_BY_FROM"
    ACCEPTED_BY_BOTH = "ACCEPTED_BY_BOTH"
    LEAGUE_APPROVED = "LEAGUE_APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class AuditSubjectType(str, Enum):
    MATCH_INCIDENT = "MATCH_INCIDENT"
    TRANSFER_OFFER = "TRANSFER_OFFER"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Mutable entities carry id + created_at + updated_at + version (PRD §2.4).
# Append-only entities carry ONLY id + created_at — no updated_at or version.
# ---------------------------------------------------------------------------


class PrizeTierEntry(TypedDict):
    placement: int
    percentage_bps: int


class BanPickStep(TypedDict):
    step: int
    team: str  # "A" | "B"
    action: str  # "BAN" | "PICK"


class SponsorEntry(TypedDict, total=False):
    name: str
    tier: str  # "GOLD" | "SILVER" | "BRONZE"


class Tournament(TypedDict, total=False):
    id: str
    name: str
    format: str
    region: str
    min_age: int
    min_team_ranking_points: int
    entry_fee_cents: int
    entry_fee_currency: str
    roster_lock_deadline: str
    registration_deadline: str
    base_prize_pool_cents: int
    crowdfunded_prize_pool_cents: int
    total_prize_pool_cents: int
    status: str
    prize_tier_table: List[PrizeTierEntry]
    ban_pick_sequence: List[BanPickStep]
    map_pool: List[str]
    character_pool: List[str]
    seeding_rule: str
    max_teams: int
    required_referee_level: str
    bracket_published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeamRegistration(TypedDict, total=False):
    id: str
    tournament_id: str
    team_name: str
    manager_id: str
    region: str
    logo_url: Optional[str]
    sponsors: List[SponsorEntry]
    seed_number: Optional[int]
    ranking_points_snapshot: Optional[int]
    entry_fee_paid_cents: int
    status: str
    roster_locked: bool
    created_at: str
    updated_at: str
    version: int


class Signature(TypedDict, total=False):
    party: str
    signed_by_user_id: str
    signed_at: str


class RequiredSignatory(TypedDict, total=False):
    party: str


class PlayerContract(TypedDict, total=False):
    id: str
    player_id: str
    player_legal_name: str
    player_age: int
    identity_verified: bool
    team_id: str
    contract_type: str
    roster_slot: str
    term_start: str
    term_end: str
    monthly_compensation_cents: int
    compensation_currency: str
    dispute_resolution_clause: str
    ranking_points: int
    required_signatories: List[RequiredSignatory]
    signatures: List[Signature]
    status: str
    signed_version_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only — id + created_at only.
class IdentityVerification(TypedDict, total=False):
    id: str
    player_id: str
    contract_id: str
    document_hash: str
    jurisdiction: str
    status: str
    rejection_reason: Optional[str]
    created_at: str


class Match(TypedDict, total=False):
    id: str
    tournament_id: str
    round_number: int
    bracket_position: int
    team_a_id: Optional[str]
    team_b_id: Optional[str]
    is_bye: bool
    scheduled_start: str
    scheduled_end: str
    status: str
    winner_team_id: Optional[str]
    forfeit_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only — id + created_at only.
class DraftEvent(TypedDict, total=False):
    id: str
    match_id: str
    step_index: int
    action: str
    side: str
    target_type: str
    target_name: str
    anomaly_type: Optional[str]
    recorded_by_user_id: str
    created_at: str


class MatchIncidentEvidence(TypedDict, total=False):
    kind: str
    uri: str
    hash: str


class MatchIncident(TypedDict, total=False):
    id: str
    match_id: str
    subject_type: str
    subject_id: str
    classification: str
    evidence: List[MatchIncidentEvidence]
    referee_id: str
    ruling: str
    penalty_type: str
    fine_amount_cents: Optional[int]
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referee(TypedDict, total=False):
    id: str
    user_id: str
    full_name: str
    certification_level: str
    certification_expiry: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only — id + created_at only.
class CrowdfundContribution(TypedDict, total=False):
    id: str
    tournament_id: str
    contributor_user_id: str
    amount_cents: int
    status: str
    created_at: str


class PrizePayout(TypedDict, total=False):
    id: str
    tournament_id: str
    team_id: Optional[str]
    player_id: Optional[str]
    award_kind: str
    placement: Optional[int]
    gross_amount_cents: int
    tax_withheld_cents: int
    net_amount_cents: int
    payout_currency: str
    jurisdiction: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferHistoryEntry(TypedDict, total=False):
    round: int
    by: str
    action: str
    terms: dict
    at: str


class TransferOffer(TypedDict, total=False):
    id: str
    player_id: str
    from_team_id: str
    to_team_id: str
    window_id: str
    transfer_fee_cents: int
    transfer_fee_currency: str
    status: str
    from_team_decision_at: Optional[str]
    to_team_decision_at: Optional[str]
    league_decision_at: Optional[str]
    history: List[TransferHistoryEntry]
    created_at: str
    updated_at: str
    version: int


class TransferWindow(TypedDict, total=False):
    id: str
    name: str
    opens_at: str
    closes_at: str
    cooling_off_days: int
    created_at: str
    updated_at: str
    version: int


# Append-only — id + created_at only.
class AuditLogEntry(TypedDict, total=False):
    id: str
    subject_type: str
    subject_id: str
    actor_user_id: str
    actor_role: str
    action: str
    payload: Any
    created_at: str


__all__ = [
    "UserRole",
    "TournamentFormat",
    "TournamentRegion",
    "TournamentStatus",
    "SeedingRule",
    "Currency",
    "TeamRegistrationStatus",
    "SponsorTier",
    "ContractType",
    "RosterSlot",
    "DisputeResolutionClause",
    "SignatoryParty",
    "PlayerContractStatus",
    "IdentityVerificationStatus",
    "MatchStatus",
    "DraftAction",
    "DraftSide",
    "DraftTargetType",
    "DraftAnomalyType",
    "IncidentSubjectType",
    "IncidentClassification",
    "IncidentEvidenceKind",
    "IncidentRuling",
    "IncidentPenaltyType",
    "IncidentStatus",
    "RefereeCertificationLevel",
    "RefereeStatus",
    "PrizeAwardKind",
    "PrizePayoutStatus",
    "CrowdfundContributionStatus",
    "TransferOfferStatus",
    "AuditSubjectType",
    "PrizeTierEntry",
    "BanPickStep",
    "SponsorEntry",
    "Tournament",
    "TeamRegistration",
    "Signature",
    "RequiredSignatory",
    "PlayerContract",
    "IdentityVerification",
    "Match",
    "DraftEvent",
    "MatchIncidentEvidence",
    "MatchIncident",
    "Referee",
    "CrowdfundContribution",
    "PrizePayout",
    "TransferHistoryEntry",
    "TransferOffer",
    "TransferWindow",
    "AuditLogEntry",
]
