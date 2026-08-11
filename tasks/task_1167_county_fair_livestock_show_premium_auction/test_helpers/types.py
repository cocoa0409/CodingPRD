"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class Species(str, Enum):
    MARKET_STEER = "MARKET_STEER"
    MARKET_SWINE = "MARKET_SWINE"
    MARKET_LAMB = "MARKET_LAMB"
    MARKET_GOAT = "MARKET_GOAT"


class FairPosture(str, Enum):
    SETUP = "SETUP"
    ENTRIES_OPEN = "ENTRIES_OPEN"
    ENTRIES_LOCKED = "ENTRIES_LOCKED"
    WEIGH_IN = "WEIGH_IN"
    SHOWING = "SHOWING"
    AUCTION = "AUCTION"
    SETTLEMENT = "SETTLEMENT"
    CLOSED = "CLOSED"


class Organization(str, Enum):
    FFA = "FFA"
    FOUR_H = "FOUR_H"
    INDEPENDENT = "INDEPENDENT"


class ExhibitorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EntryStatus(str, Enum):
    ENTERED = "ENTERED"
    VERIFIED = "VERIFIED"
    WEIGHED = "WEIGHED"
    CLASSIFIED = "CLASSIFIED"
    SHOWN = "SHOWN"
    SOLD = "SOLD"
    NOT_SOLD = "NOT_SOLD"
    DISQUALIFIED = "DISQUALIFIED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class WeighTicketStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ClassStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class SlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class PlacingAward(str, Enum):
    NONE = "NONE"
    GRAND_CHAMPION = "GRAND_CHAMPION"
    RESERVE_CHAMPION = "RESERVE_CHAMPION"


class PlacingStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class PremiumAwardStatus(str, Enum):
    ACCRUED = "ACCRUED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    FORFEITED = "FORFEITED"


class LotStatus(str, Enum):
    QUEUED = "QUEUED"
    OPEN = "OPEN"
    SOLD = "SOLD"
    PASSED = "PASSED"
    NO_SALE = "NO_SALE"


class AddOnStatus(str, Enum):
    PLEDGED = "PLEDGED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class DispositionType(str, Enum):
    HARVEST = "HARVEST"
    RETURN = "RETURN"


class DispositionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    QUARANTINE = "QUARANTINE"


class AffidavitStatus(str, Enum):
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class UserRole(str, Enum):
    FAIR_BOARD_ADMIN = "FairBoardAdmin"
    EXHIBITOR = "Exhibitor"
    WEIGH_MASTER = "WeighMaster"
    SHOW_CLERK = "ShowClerk"
    JUDGE = "Judge"
    AUCTIONEER = "Auctioneer"
    BUYER = "Buyer"
    HEALTH_INSPECTOR = "HealthInspector"
    TREASURER = "Treasurer"


class Fair(TypedDict, total=False):
    id: str
    name: str
    ownership_deadline_at: str
    possession_deadline_at: str
    premium_budget_cents: int
    available_premium_pool_cents: int
    commission_rate: float
    buyer_premium_rate: float
    yardage_fee_cents: int
    premium_cap_cents: int
    large_class_min_entries: int
    large_class_bonus_rate: float
    premium_schedule: dict
    state_qualify_rank: dict
    sale_rank_threshold: dict
    species_sale_order: List[str]
    posture: str
    created_at: str
    updated_at: str
    version: int


class Exhibitor(TypedDict, total=False):
    id: str
    fair_id: str
    full_name: str
    organization: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AnimalEntry(TypedDict, total=False):
    id: str
    fair_id: str
    exhibitor_id: str
    species: str
    tag_number: str
    ownership_acquired_at: str
    possession_start_at: str
    official_weight_lbs: Optional[float]
    class_id: Optional[str]
    state_fair_qualified: bool
    status: str
    disqualification_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WeighTicket(TypedDict, total=False):
    id: str
    entry_id: str
    weight_lbs: float
    weighed_at: str
    scale_identifier: Optional[str]
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShowClass(TypedDict, total=False):
    id: str
    fair_id: str
    species: str
    class_code: str
    weight_min_lbs: float
    weight_max_lbs: float
    capacity: int
    placed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Judge(TypedDict, total=False):
    id: str
    fair_id: str
    full_name: str
    qualified_species: List[str]
    created_at: str
    updated_at: str
    version: int


class RingSlot(TypedDict, total=False):
    id: str
    fair_id: str
    class_id: str
    ring_name: str
    starts_at: str
    ends_at: str
    judge_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Placing(TypedDict, total=False):
    id: str
    ring_slot_id: str
    class_id: str
    entry_id: str
    rank: int
    award: str
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PremiumAward(TypedDict, total=False):
    id: str
    entry_id: str
    placing_id: str
    provisional_amount_cents: int
    final_amount_cents: Optional[int]
    status: str
    approved_by_user_id: Optional[str]
    paid_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict, total=False):
    id: str
    fair_id: str
    business_name: str
    bidder_number: str
    credit_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class AuctionLot(TypedDict, total=False):
    id: str
    fair_id: str
    entry_id: str
    lot_number: int
    status: str
    buyer_id: Optional[str]
    hammer_price_cents: Optional[int]
    invoice_id: Optional[str]
    reoffer_count: int
    provisional_payout_cents: Optional[int]
    final_payout_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AddOnPledge(TypedDict, total=False):
    id: str
    lot_id: str
    buyer_id: str
    invoice_id: Optional[str]
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    fair_id: str
    buyer_id: str
    status: str
    hammer_subtotal_cents: int
    addon_subtotal_cents: int
    buyer_premium_cents: int
    total_due_cents: int
    amount_paid_cents: int
    balance_cents: int
    line_count: int
    created_at: str
    updated_at: str
    version: int


class DispositionOrder(TypedDict, total=False):
    id: str
    entry_id: str
    disposition_type: str
    destination: Optional[str]
    scheduled_date: Optional[str]
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable record (PRD §2.4): carries only id + created_at — no updated_at, no version.
class HealthInspection(TypedDict, total=False):
    id: str
    entry_id: str
    result: str
    notes: Optional[str]
    created_at: str


class Affidavit(TypedDict, total=False):
    id: str
    entry_id: str
    exhibitor_id: str
    signed_at: str
    withdrawal_end_date: Optional[str]
    status: str
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
