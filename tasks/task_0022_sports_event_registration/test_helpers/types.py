"""Domain types for the Sports Event Registration API.

Status enums and entity TypedDicts derived from PRD §2.4 (Common Resource
Properties) and the entity / state-machine prose in §3. Entities carrying
write-once semantics per PRD §2.4 — ResultEntry, SanctionRecord, AuditLog,
SyncEvent — expose only `id` and `created_at`; all other entities carry the
full common-fields quartet (`id`, `created_at`, `updated_at`, `version`).
"""
from __future__ import annotations
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ORGANIZER = "Organizer"
    REFEREE = "Referee"
    PARTICIPANT = "Participant"
    DISCIPLINARY_OFFICER = "DisciplinaryOfficer"
    DOPING_OFFICER = "DopingOfficer"
    APPEALS_BOARD = "AppealsBoard"


# ---------------------------------------------------------------------------
# Discipline / event_type
# ---------------------------------------------------------------------------
class EventType(str, Enum):
    SINGLE_ELIM = "SINGLE_ELIM"
    ROUND_ROBIN = "ROUND_ROBIN"
    SETS_MATCH = "SETS_MATCH"


class SettlementCurrency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    JPY = "JPY"
    GBP = "GBP"


class Region(str, Enum):
    AFC = "AFC"
    CAF = "CAF"
    CONCACAF = "CONCACAF"
    CONMEBOL = "CONMEBOL"
    OFC = "OFC"
    UEFA = "UEFA"


# ---------------------------------------------------------------------------
# Entity status enums (PRD §3 prose; one per entity with a state machine)
# ---------------------------------------------------------------------------
class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    REGISTRATION_CLOSED = "REGISTRATION_CLOSED"
    DRAWN = "DRAWN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EventPosture(str, Enum):
    CLEAN = "CLEAN"
    UNDER_REVIEW = "UNDER_REVIEW"
    FROZEN = "FROZEN"


class ParticipantStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SEEDED = "SEEDED"
    ACTIVE = "ACTIVE"
    ELIMINATED = "ELIMINATED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class MatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RESULT_PENDING = "RESULT_PENDING"
    DISPUTED = "DISPUTED"
    LOCKED = "LOCKED"
    BYE = "BYE"
    VOIDED = "VOIDED"


class RefereeRole(str, Enum):
    HEAD = "HEAD"
    ASSISTANT = "ASSISTANT"
    SUBSTITUTE = "SUBSTITUTE"


class RefereeGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class RefereeAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    REVOKED = "REVOKED"
    ACTIVATED = "ACTIVATED"


class ResultEntryKind(str, Enum):
    REFEREE_SUBMISSION = "REFEREE_SUBMISSION"
    CORRECTION = "CORRECTION"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class DopingSampleStatus(str, Enum):
    COLLECTED = "COLLECTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    NEGATIVE = "NEGATIVE"
    POSITIVE = "POSITIVE"
    VOIDED = "VOIDED"


class CustodyAction(str, Enum):
    DISPATCH = "DISPATCH"
    RECEIVE = "RECEIVE"


class SanctionStatus(str, Enum):
    ISSUED = "ISSUED"
    APPEALED = "APPEALED"
    FINAL = "FINAL"
    REVOKED = "REVOKED"


class AppealStatus(str, Enum):
    PENDING = "PENDING"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class PrizePaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    FORFEITED = "FORFEITED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class AuditLogKind(str, Enum):
    RESULT_CHANGE = "RESULT_CHANGE"
    SANCTION_CHANGE = "SANCTION_CHANGE"


class AuditLogSubjectKind(str, Enum):
    MATCH = "MATCH"
    SANCTION_RECORD = "SANCTION_RECORD"


class SyncEventTargetSystem(str, Enum):
    PAYMENT = "PAYMENT"
    GOVERNING_BODY = "GOVERNING_BODY"
    IM = "IM"


class SyncEventKind(str, Enum):
    ENTRY_FEE_CHARGED = "ENTRY_FEE_CHARGED"
    PRIZE_PAID = "PRIZE_PAID"
    SANCTION_ARCHIVED = "SANCTION_ARCHIVED"
    DRAW_ANNOUNCED = "DRAW_ANNOUNCED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# PRD §2.4 — the bare list (only id + created_at) is: ResultEntry,
# SanctionRecord, AuditLog, SyncEvent.
# ---------------------------------------------------------------------------
class Event(TypedDict, total=False):
    id: str
    name: str
    event_type: str
    country_code: str
    regulations_text: str
    registration_opens_at: str
    registration_closes_at: str
    starts_at: str
    entry_fee_cents: int
    settlement_currency: str
    capacity_min: int
    capacity_max: int
    prize_pool_cents: int
    tax_withholding_pct: float
    status: str
    registered_count: int
    prize_paid_total_cents: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict, total=False):
    id: str
    event_id: str
    athlete_external_id: str
    display_name: str
    team_code: Optional[str]
    country_code: str
    world_ranking: Optional[int]
    region: str
    entry_fee_paid_cents: int
    status: str
    bracket_seed: Optional[int]
    gross_prize_cents: int
    net_prize_cents: int
    final_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Referee(TypedDict, total=False):
    id: str
    full_name: str
    country_code: str
    team_affiliation: Optional[str]
    qualifications: List[str]
    grade: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict, total=False):
    id: str
    event_id: str
    round_index: int
    bracket_position: int
    home_participant_id: Optional[str]
    away_participant_id: Optional[str]
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    locked_home_score: Optional[int]
    locked_away_score: Optional[int]
    locked_home_sets_won: Optional[int]
    locked_away_sets_won: Optional[int]
    winner_participant_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefereeAssignment(TypedDict, total=False):
    id: str
    match_id: str
    referee_id: str
    role: str
    status: str
    replaces_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Write-once entity per PRD §2.4 — only id + created_at.
class ResultEntry(TypedDict, total=False):
    id: str
    match_id: str
    submitted_by_assignment_id: str
    home_score: int
    away_score: int
    home_sets_won: Optional[int]
    away_sets_won: Optional[int]
    kind: str
    superseded_by_id: Optional[str]
    created_at: str


class Dispute(TypedDict, total=False):
    id: str
    match_id: str
    filed_by_participant_id: str
    reason_text: str
    status: str
    corrected_result_entry_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RankingEntry(TypedDict, total=False):
    id: str
    event_id: str
    participant_id: str
    points: int
    goal_difference: int
    away_goals: int
    sets_won: int
    provisional_rank: Optional[int]
    final_rank: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PrizePayment(TypedDict, total=False):
    id: str
    event_id: str
    participant_id: str
    gross_amount_cents: int
    tax_withheld_cents: int
    forfeit_amount_cents: int
    net_amount_cents: int
    scheduled_pay_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DopingSample(TypedDict, total=False):
    id: str
    event_id: str
    participant_id: str
    collected_at: str
    chain_log: List[dict]
    status: str
    result_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Write-once entity per PRD §2.4 — only id + created_at.
class SanctionRecord(TypedDict, total=False):
    id: str
    sample_id: str
    participant_id: str
    ban_months: int
    prize_forfeited_cents: int
    status: str
    created_at: str


class Appeal(TypedDict, total=False):
    id: str
    sanction_id: str
    filed_by_user_id: str
    ground_text: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Write-once entity per PRD §2.4 — only id + created_at.
class AuditLog(TypedDict, total=False):
    id: str
    kind: str
    subject_kind: str
    subject_id: str
    actor_user_id: str
    actor_role: str
    from_value: Any
    to_value: Any
    created_at: str


# Write-once entity per PRD §2.4 — only id + created_at.
class SyncEvent(TypedDict, total=False):
    id: str
    target_system: str
    kind: str
    payload: Any
    emitted_at: str
    created_at: str


__all__ = [
    "UserRole",
    "EventType",
    "SettlementCurrency",
    "Region",
    "EventStatus",
    "EventPosture",
    "ParticipantStatus",
    "MatchStatus",
    "RefereeRole",
    "RefereeGrade",
    "RefereeAssignmentStatus",
    "ResultEntryKind",
    "DisputeStatus",
    "DopingSampleStatus",
    "CustodyAction",
    "SanctionStatus",
    "AppealStatus",
    "PrizePaymentStatus",
    "AuditLogKind",
    "AuditLogSubjectKind",
    "SyncEventTargetSystem",
    "SyncEventKind",
    "Event",
    "Participant",
    "Referee",
    "Match",
    "RefereeAssignment",
    "ResultEntry",
    "Dispute",
    "RankingEntry",
    "PrizePayment",
    "DopingSample",
    "SanctionRecord",
    "Appeal",
    "AuditLog",
    "SyncEvent",
]
