"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    COMMITTEE_ADMIN = "CommitteeAdmin"
    ENTRY_OFFICE = "EntryOffice"
    CONTESTANT = "Contestant"
    JUDGE = "Judge"
    VETERINARIAN = "Veterinarian"
    BOX_OFFICE = "BoxOffice"


class RodeoPosture(str, Enum):
    DRAFT = "DRAFT"
    ENTRIES_OPEN = "ENTRIES_OPEN"
    DRAW_LOCKED = "DRAW_LOCKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class EventCode(str, Enum):
    BAREBACK = "BAREBACK"
    SADDLE_BRONC = "SADDLE_BRONC"
    BULL_RIDING = "BULL_RIDING"
    TIE_DOWN_ROPING = "TIE_DOWN_ROPING"
    STEER_WRESTLING = "STEER_WRESTLING"
    TEAM_ROPING = "TEAM_ROPING"
    BARREL_RACING = "BARREL_RACING"


class Discipline(str, Enum):
    ROUGH_STOCK = "ROUGH_STOCK"
    TIMED = "TIMED"


class PerformanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ContestantStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    SUSPENDED = "SUSPENDED"


class ContractStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    TERMINATED = "TERMINATED"


class AnimalStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DRAWN = "DRAWN"
    COMPETED = "COMPETED"
    INJURED = "INJURED"
    RETIRED = "RETIRED"


class JudgeCertification(str, Enum):
    PRCA_CARD = "PRCA_CARD"
    PRCA_GOLD = "PRCA_GOLD"


class JudgePosition(str, Enum):
    ARENA_1 = "ARENA_1"
    ARENA_2 = "ARENA_2"
    BARRIER = "BARRIER"
    TIMER = "TIMER"


class EntryStatus(str, Enum):
    ENTERED = "ENTERED"
    WAITLISTED = "WAITLISTED"
    DRAWN = "DRAWN"
    TURNED_OUT = "TURNED_OUT"
    DRAWN_OUT = "DRAWN_OUT"
    CANCELLED = "CANCELLED"
    COMPETED = "COMPETED"


class TurnOutReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    MEDICAL = "MEDICAL"


class DrawAssignmentStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class ResultStatus(str, Enum):
    RECORDED = "RECORDED"
    VERIFIED = "VERIFIED"
    AMENDED = "AMENDED"
    VOIDED = "VOIDED"


class ResultOutcome(str, Enum):
    QUALIFIED = "QUALIFIED"
    DISQUALIFIED = "DISQUALIFIED"
    NO_SCORE = "NO_SCORE"
    NO_TIME = "NO_TIME"


class PayoutStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    DISBURSED = "DISBURSED"


class PayoutVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class SettlementBasis(str, Enum):
    DAY_RATE = "DAY_RATE"
    PER_OUT = "PER_OUT"


class VetSubjectType(str, Enum):
    ANIMAL = "ANIMAL"
    CONTESTANT = "CONTESTANT"


class VetDisposition(str, Enum):
    CLEARED = "CLEARED"
    INJURED_TURNOUT = "INJURED_TURNOUT"
    RETIRED = "RETIRED"


class TicketOrderStatus(str, Enum):
    PAID = "PAID"
    REFUNDED = "REFUNDED"


# --- Entity TypedDicts -------------------------------------------------------
# All resources except vet reports carry the standard system-managed fields
# id / created_at / updated_at / version (PRD §2.5). Vet reports are the one
# exception: they carry id and created_at only (PRD §2.5).


class Rodeo(TypedDict):
    id: str
    name: str
    city: str
    entries_close_at: str
    posture: str
    unclaimed_purse_cents: int
    created_at: str
    updated_at: str
    version: int


class RodeoEvent(TypedDict):
    id: str
    rodeo_id: str
    event_code: str
    discipline: str
    go_rounds: int
    entry_fee_cents: int
    added_money_cents: int
    per_performance_slots: int
    payout_places: int
    drawn_rounds: List[int]
    created_at: str
    updated_at: str
    version: int


class Performance(TypedDict):
    id: str
    rodeo_id: str
    label: str
    arena: str
    starts_at: str
    ends_at: str
    arena_capacity: int
    sold_tickets: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Contestant(TypedDict):
    id: str
    card_number: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StockContract(TypedDict):
    id: str
    rodeo_id: str
    contractor_name: str
    day_rate_cents: int
    per_out_fee_cents: int
    status: str
    day_rate_total_cents: int
    per_out_total_cents: int
    settlement_cents: int
    settlement_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StockAnimal(TypedDict):
    id: str
    contract_id: str
    tag_number: str
    event_code: str
    welfare_out_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict):
    id: str
    card_number: str
    full_name: str
    certification: str
    created_at: str
    updated_at: str
    version: int


class JudgeAssignment(TypedDict):
    id: str
    judge_id: str
    performance_id: str
    position: str
    created_at: str
    updated_at: str
    version: int


class Entry(TypedDict):
    id: str
    contestant_id: str
    rodeo_event_id: str
    status: str
    entry_fee_cents: int
    purse_contribution_cents: int
    committee_retention_cents: int
    sanction_fee_cents: int
    fee_charges_cents: int
    contribution_charges_cents: int
    refunded_cents: int
    refunded_contribution_cents: int
    turn_out_reason: Optional[str]
    vet_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrawAssignment(TypedDict):
    id: str
    entry_id: str
    rodeo_event_id: str
    go_round_number: int
    performance_id: str
    animal_id: Optional[str]
    draw_position: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RunResult(TypedDict):
    id: str
    draw_assignment_id: str
    entry_id: str
    rodeo_event_id: str
    judge_id: str
    judge_1_score: Optional[int]
    judge_2_score: Optional[int]
    raw_time_ms: Optional[int]
    penalty_ms: Optional[int]
    qualified_flag: bool
    disqualified_flag: bool
    outcome: str
    total_score: Optional[int]
    total_time_ms: Optional[int]
    status: str
    amendment_reason: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlaceLine(TypedDict):
    scope: str
    place: int
    contestant_id: str
    amount_cents: int
    tied_count: int


class GoRoundPool(TypedDict):
    go_round: int
    pool_cents: int


class Payout(TypedDict):
    id: str
    rodeo_event_id: str
    computed_variant: str
    purse_cents: int
    go_round_pools: List[GoRoundPool]
    average_pool_cents: int
    place_lines: List[PlaceLine]
    status: str
    created_at: str
    updated_at: str
    version: int


class VetReport(TypedDict):
    # Append-only (PRD §2.5): carries id and created_at ONLY —
    # no updated_at, no version.
    id: str
    subject_type: str
    animal_id: Optional[str]
    contestant_id: Optional[str]
    performance_id: Optional[str]
    findings: str
    disposition: str
    veterinarian_name: str
    created_at: str


class TicketOrder(TypedDict):
    id: str
    performance_id: str
    section: str
    quantity: int
    unit_price_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
