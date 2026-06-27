"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system are mutable system-of-record objects carrying
id + created_at + updated_at + version (see PRD 2.4).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    LICENSING_ADMIN = "LicensingAdmin"
    TERMINAL_OPERATOR = "TerminalOperator"
    CLAIMS_CLERK = "ClaimsClerk"
    LOTTERY_OFFICER = "LotteryOfficer"


# --- Status enums ---
class GameStatus(str, Enum):
    ACTIVE = "ACTIVE"


class GameType(str, Enum):
    JACKPOT = "JACKPOT"
    INSTANT = "INSTANT"
    DAILY = "DAILY"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class TerminalStatus(str, Enum):
    PROVISIONED = "PROVISIONED"
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class SelfExclusionStatus(str, Enum):
    NONE = "NONE"
    EXCLUDED = "EXCLUDED"
    REINSTATED = "REINSTATED"


class ValidationStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    VALIDATED_WINNER = "VALIDATED_WINNER"
    VALIDATED_NONWINNER = "VALIDATED_NONWINNER"
    PAID_AT_COUNTER = "PAID_AT_COUNTER"
    COUNTER_REVERSED = "COUNTER_REVERSED"
    CLAIM_PENDING = "CLAIM_PENDING"
    REJECTED = "REJECTED"
    ESCHEATED = "ESCHEATED"


class SecondChanceStatus(str, Enum):
    INELIGIBLE = "INELIGIBLE"
    ELIGIBLE = "ELIGIBLE"
    ENTERED = "ENTERED"
    DRAWN_WINNER = "DRAWN_WINNER"
    DRAWN_LOSER = "DRAWN_LOSER"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATING = "ADJUDICATING"
    APPROVED_CASH = "APPROVED_CASH"
    APPROVED_ANNUITY = "APPROVED_ANNUITY"
    PAID = "PAID"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class DrawingStatus(str, Enum):
    OPEN = "OPEN"
    DRAWN = "DRAWN"
    CANCELLED = "CANCELLED"


class EntryOutcome(str, Enum):
    PENDING = "PENDING"
    WON = "WON"
    LOST = "LOST"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


# --- Entity TypedDicts (all common_fields: true → id+created_at+updated_at+version) ---
class DrawingGame(TypedDict):
    id: str
    name: str
    game_type: str
    claim_window_days: int
    federal_withholding_threshold_cents: int
    federal_withholding_rate: float
    state_withholding_rate: float
    cash_option_factor: float
    annuity_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Retailer(TypedDict):
    id: str
    business_name: str
    tax_id: str
    commission_rate: float
    cashing_bonus_rate: float
    license_status: str
    commission_balance_cents: int
    lifetime_settled_cents: int
    created_at: str
    updated_at: str
    version: int


class Terminal(TypedDict):
    id: str
    retailer_id: str
    serial_number: str
    status: str
    tickets_sold_count: int
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    full_name: str
    government_id_number: str
    self_exclusion_status: str
    exclusion_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    game_id: str
    terminal_id: str
    serial: str
    price_cents: int
    draw_date: str
    declared_tier: int
    gross_prize_cents: int
    validation_status: str
    second_chance_status: str
    claim_deadline: str
    created_at: str
    updated_at: str
    version: int


class PrizeClaim(TypedDict):
    id: str
    ticket_id: str
    player_id: str
    adjudicated_by_user_id: Optional[str]
    disbursed_by_user_id: Optional[str]
    payout_option: str
    gross_payout_cents: int
    federal_withholding_cents: int
    state_withholding_cents: int
    net_payout_cents: int
    annual_installment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SecondChanceDrawing(TypedDict):
    id: str
    game_id: str
    entry_deadline: str
    prize_pool_cents: int
    entry_count: int
    winning_entry_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SecondChanceEntry(TypedDict):
    id: str
    drawing_id: str
    ticket_id: str
    entered_at: str
    outcome: str
    created_at: str
    updated_at: str
    version: int


class CommissionSettlement(TypedDict):
    id: str
    retailer_id: str
    period_start: str
    period_end: str
    prepared_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    gross_commission_cents: int
    clawback_cents: int
    net_settlement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EscheatRecord(TypedDict):
    id: str
    ticket_id: str
    escheated_amount_cents: int
    escheated_at: str
    created_at: str
    updated_at: str
    version: int
