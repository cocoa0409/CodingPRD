"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow PRD §2.4: primary resources carry id + created_at +
updated_at + version. Append-only records (TicketSale, AncillaryRevenue,
CancellationEvent) carry only id + created_at; updated_at and version
are absent from those three.
"""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class ArtistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ShowStatus(str, Enum):
    HOLD_PENDING = "HOLD_PENDING"
    CONFIRMED = "CONFIRMED"
    ON_SALE = "ON_SALE"
    ADVANCED = "ADVANCED"
    SHOW_NIGHT = "SHOW_NIGHT"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"
    POSTPONED = "POSTPONED"


class HoldPriority(str, Enum):
    NONE = "NONE"
    P1 = "P1"
    P2 = "P2"
    COURTESY = "COURTESY"


class HoldInputPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    COURTESY = "COURTESY"


class DateHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CHALLENGED = "CHALLENGED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class BookingAgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Room(str, Enum):
    MAIN_ROOM = "MAIN_ROOM"
    LOUNGE = "LOUNGE"


class DealKind(str, Enum):
    FLAT_GUARANTEE = "FLAT_GUARANTEE"
    DOOR_SPLIT = "DOOR_SPLIT"
    VERSUS = "VERSUS"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class OfferProposedByRole(str, Enum):
    BOOKING_AGENT = "BOOKING_AGENT"
    VENUE_MANAGER = "VENUE_MANAGER"


class DealStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class RefundStatus(str, Enum):
    NONE = "NONE"
    REFUNDED = "REFUNDED"


class SupportActStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PERFORMED = "PERFORMED"
    BOUGHT_OUT = "BOUGHT_OUT"
    CANCELLED = "CANCELLED"


class ExpenseCategory(str, Enum):
    SOUND = "SOUND"
    LIGHTS = "LIGHTS"
    BACKLINE = "BACKLINE"
    HOSPITALITY = "HOSPITALITY"
    SECURITY = "SECURITY"
    MARKETING = "MARKETING"
    MISC = "MISC"


class ExpenseReceiptStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class SubmittedByRole(str, Enum):
    PROMOTER = "PROMOTER"
    VENUE_MANAGER = "VENUE_MANAGER"


class AncillaryKind(str, Enum):
    BAR = "BAR"
    MERCH = "MERCH"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class WirePurpose(str, Enum):
    ARTIST_DEPOSIT = "ARTIST_DEPOSIT"
    ARTIST_BALANCE = "ARTIST_BALANCE"
    SUPPORT_FEE = "SUPPORT_FEE"
    SUPPORT_BUYOUT = "SUPPORT_BUYOUT"
    REFUND_TO_VENUE = "REFUND_TO_VENUE"


class WireStatus(str, Enum):
    INITIATED = "INITIATED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETURNED = "RETURNED"


class CancellationReason(str, Enum):
    NONE = "NONE"
    ARTIST = "ARTIST"
    VENUE = "VENUE"
    FORCE_MAJEURE = "FORCE_MAJEURE"
    LOW_TICKET_SALES = "LOW_TICKET_SALES"


class DeclaredByRole(str, Enum):
    BOOKING_AGENT = "BOOKING_AGENT"
    VENUE_MANAGER = "VENUE_MANAGER"
    PROMOTER = "PROMOTER"


class UserRole(str, Enum):
    VENUE_MANAGER = "VenueManager"
    BOOKING_AGENT = "BookingAgent"
    PROMOTER = "Promoter"
    PRODUCTION_MANAGER = "ProductionManager"
    ACCOUNTANT = "Accountant"


# ---------------------------------------------------------------------------
# Entity shapes (primary resources carry id/created_at/updated_at/version)
# ---------------------------------------------------------------------------

class Artist(TypedDict, total=False):
    id: str
    legal_name: str
    agency: str
    guarantee_floor_cents: int
    deposit_pct: float
    status: str
    total_settled_shows: int
    created_at: str
    updated_at: str
    version: int


class Show(TypedDict, total=False):
    id: str
    artist_id: str
    room: str
    show_date: str
    doors_at_utc: str
    curfew_at_utc: str
    status: str
    hold_priority: str
    deal_id: Optional[str]
    deposit_required_cents: int
    deposit_paid_cents: int
    deposit_due_by_utc: str
    total_capacity: int
    tickets_sold: int
    gross_ticket_revenue_cents: int
    on_sale_at_utc: str
    weather_or_emergency_flag: bool
    cancellation_reason: str
    created_at: str
    updated_at: str
    version: int


class DateHold(TypedDict, total=False):
    id: str
    show_id: str
    priority: str
    status: str
    hold_expires_at_utc: str
    challenge_window_ends_at_utc: Optional[str]
    booked_by_agent_id: str
    created_at: str
    updated_at: str
    version: int


class BookingAgent(TypedDict, total=False):
    id: str
    display_name: str
    agency_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict, total=False):
    id: str
    show_id: str
    round_number: int
    proposed_by_role: str
    deal_kind: str
    guarantee_cents: int
    artist_split_pct: float
    versus_threshold_cents: int
    status: str
    expense_budget_cents: int
    support_budget_cents: int
    bar_split_pct: float
    merch_split_pct: float
    supersedes_offer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict, total=False):
    id: str
    show_id: str
    offer_id: str
    deal_kind: str
    guarantee_cents: int
    artist_split_pct: float
    versus_threshold_cents: int
    expense_budget_cents: int
    support_budget_cents: int
    bar_split_pct: float
    merch_split_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TicketTier(TypedDict, total=False):
    id: str
    show_id: str
    tier_name: str
    face_price_cents: int
    capacity: int
    sold_count: int
    refund_count: int
    tier_order: int
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): only id + created_at; NO updated_at, NO version.
class TicketSale(TypedDict, total=False):
    id: str
    show_id: str
    tier_id: str
    quantity: int
    gross_amount_cents: int
    sold_at_utc: str
    refund_status: str
    created_at: str


class AdvanceChecklist(TypedDict, total=False):
    id: str
    show_id: str
    hospitality_done: bool
    tech_done: bool
    backline_done: bool
    production_requirements_done: bool
    insurance_cert_received: bool
    w9_received: bool
    all_complete: bool
    created_at: str
    updated_at: str
    version: int


class SupportAct(TypedDict, total=False):
    id: str
    show_id: str
    artist_name: str
    agreed_fee_cents: int
    buyout_fee_cents: int
    status: str
    paid_cents: int
    created_at: str
    updated_at: str
    version: int


class ExpenseReceipt(TypedDict, total=False):
    id: str
    show_id: str
    category: str
    amount_cents: int
    receipt_reference: str
    submitted_by_role: str
    status: str
    rejection_reason: Optional[str]
    is_recoupable: bool
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): only id + created_at; NO updated_at, NO version.
class AncillaryRevenue(TypedDict, total=False):
    id: str
    show_id: str
    kind: str
    gross_cents: int
    cost_cents: int
    recorded_by_role: str
    recorded_at_utc: str
    created_at: str


class Settlement(TypedDict, total=False):
    id: str
    show_id: str
    status: str
    gross_ticket_revenue_cents: int
    recoupable_expenses_cents: int
    net_door_cents: int
    artist_door_share_cents: int
    guarantee_paid_cents: int
    bonus_cents: int
    bar_artist_share_cents: int
    merch_venue_share_cents: int
    support_payouts_cents: int
    deposit_credit_cents: int
    artist_total_due_cents: int
    venue_net_cents: int
    submitted_at_utc: Optional[str]
    approved_by_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WireTransfer(TypedDict, total=False):
    id: str
    show_id: str
    purpose: str
    amount_cents: int
    recipient_artist_id: Optional[str]
    support_act_id: Optional[str]
    status: str
    initiated_by_role: str
    initiated_at_utc: str
    completed_at_utc: Optional[str]
    failure_reason: Optional[str]
    settlement_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only (PRD §2.4): only id + created_at; NO updated_at, NO version.
class CancellationEvent(TypedDict, total=False):
    id: str
    show_id: str
    reason: str
    declared_by_role: str
    declared_at_utc: str
    days_before_show: int
    artist_penalty_pct: float
    artist_penalty_cents: int
    deposit_refundable_cents: int
    support_kill_fee_cents: int
    created_at: str
