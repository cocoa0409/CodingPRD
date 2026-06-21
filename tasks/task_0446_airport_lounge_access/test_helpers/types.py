"""Domain types: entity TypedDicts, status enums, role enum.

Entities that carry the standard system-managed quartet (PRD §2.4) expose
id/created_at/updated_at/version. Settlement and LedgerEntry are append-only
event records (PRD §2.4) and carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ────────────────────────────────────────────────────
class UserRole(str, Enum):
    NETWORK_ADMIN = "NetworkAdmin"
    LOUNGE_AGENT = "LoungeAgent"
    MEMBER = "Member"


# ─── Status / enum value sets ────────────────────────────────────────────────
class LoungeStatus(str, Enum):
    OPEN = "OPEN"
    OVERFLOW = "OVERFLOW"
    CLOSED = "CLOSED"


class VisitStatus(str, Enum):
    HELD = "HELD"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"
    ABANDONED = "ABANDONED"


class EntryMode(str, Enum):
    ALLOTMENT = "ALLOTMENT"
    OVERAGE = "OVERAGE"
    DAY_PASS = "DAY_PASS"


class MemberStanding(str, Enum):
    GOOD = "GOOD"
    SUSPENDED = "SUSPENDED"


class CardStatus(str, Enum):
    BASIC = "BASIC"
    SILVER = "SILVER"
    GOLD = "GOLD"


class FareClass(str, Enum):
    ECONOMY = "ECONOMY"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class PlanTier(str, Enum):
    STANDARD = "STANDARD"
    PRESTIGE = "PRESTIGE"
    PRESTIGE_PLUS = "PRESTIGE_PLUS"


class DayPassStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"


class GuestFunding(str, Enum):
    GUEST_ALLOTMENT = "GUEST_ALLOTMENT"
    GUEST_CHARGE = "GUEST_CHARGE"


class SettlementStatus(str, Enum):
    PAYABLE = "PAYABLE"
    PAID = "PAID"
    REVERSED = "REVERSED"


class LedgerKind(str, Enum):
    OVERAGE = "OVERAGE"
    GUEST_CHARGE = "GUEST_CHARGE"
    LOUNGE_GUEST_FEE = "LOUNGE_GUEST_FEE"
    DAY_PASS = "DAY_PASS"
    OVERAGE_REVERSAL = "OVERAGE_REVERSAL"
    DAY_PASS_REFUND = "DAY_PASS_REFUND"


class LedgerStatus(str, Enum):
    POSTED = "POSTED"
    VOID = "VOID"


class ShowerReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


# ─── Entity TypedDicts (quartet-carrying) ────────────────────────────────────
class MembershipPlan(TypedDict):
    id: str
    tier: str
    included_visits_per_year: int
    included_guest_visits_per_year: int
    overage_charge_cents: int
    guest_charge_cents: int
    min_card_status: str
    annual_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Lounge(TypedDict):
    id: str
    name: str
    airport_code: str
    capacity: int
    settlement_rate_cents: int
    guest_fee_cents: int
    day_pass_price_cents: int
    status: str
    current_occupancy: int
    held_occupancy: int
    settlement_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    plan_id: str
    full_name: str
    membership_year_start: str
    visits_used: int
    guest_visits_used: int
    standing: str
    no_show_strikes: int
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class EligibilityCard(TypedDict):
    id: str
    member_id: str
    card_status: str
    fare_class: str
    active: bool
    valid_until: str
    created_at: str
    updated_at: str
    version: int


class Visit(TypedDict):
    id: str
    member_id: Optional[str]
    lounge_id: str
    eligibility_card_id: Optional[str]
    day_pass_id: Optional[str]
    entry_mode: str
    guest_count: int
    occupant_count: int
    allotment_consumed: bool
    guest_allotment_consumed: int
    status: str
    held_at: str
    hold_expires_at: str
    member_charge_cents: int
    settlement_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    visit_id: str
    full_name: str
    funded_by: str
    charge_cents: int
    created_at: str
    updated_at: str
    version: int


class DayPass(TypedDict):
    id: str
    lounge_id: str
    member_id: Optional[str]
    buyer_name: Optional[str]
    price_cents: int
    status: str
    valid_until: str
    redeemed_visit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShowerSuite(TypedDict):
    id: str
    lounge_id: str
    label: str
    turnover_minutes: int
    out_of_service: bool
    created_at: str
    updated_at: str
    version: int


class ShowerReservation(TypedDict):
    id: str
    shower_suite_id: str
    visit_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only event records (id + created_at only) ────────────────────────
class Settlement(TypedDict):
    id: str
    lounge_id: str
    visit_id: str
    amount_cents: int
    status: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    member_id: str
    visit_id: Optional[str]
    day_pass_id: Optional[str]
    kind: str
    amount_cents: int
    status: str
    created_at: str
