"""Domain types for the Fundraising Gala & Auction API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them. Every resource in this system carries id, created_at,
updated_at and version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ──────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    EVENT_ORGANIZER = "EventOrganizer"
    AUCTION_MANAGER = "AuctionManager"
    FINANCE_OFFICER = "FinanceOfficer"
    BIDDER = "Bidder"
    SPONSOR = "Sponsor"


# ─── Status / enum vocabularies ─────────────────────────────────────────────

class GalaEventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LIVE = "LIVE"
    SETTLING = "SETTLING"
    CLOSED = "CLOSED"


class GalaEventPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class TicketTableStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SOLD_OUT = "SOLD_OUT"


class TableHoldStatus(str, Enum):
    HELD = "HELD"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class TicketOrderType(str, Enum):
    TABLE = "TABLE"
    SEAT = "SEAT"


class TicketOrderPaymentStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class TicketOrderSeatingStatus(str, Enum):
    UNSEATED = "UNSEATED"
    SEATED = "SEATED"
    RELEASED = "RELEASED"


class SponsorTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"


class SponsorStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class AdSize(str, Enum):
    FULL_PAGE = "FULL_PAGE"
    HALF_PAGE = "HALF_PAGE"
    QUARTER_PAGE = "QUARTER_PAGE"


class ProgramAdStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PLACED = "PLACED"


class AdReviewDecision(str, Enum):
    BEGIN_REVIEW = "BEGIN_REVIEW"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class AuctionItemType(str, Enum):
    SILENT = "SILENT"
    LIVE = "LIVE"


class AuctionItemListingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    PASSED = "PASSED"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class ValuationVariant(str, Enum):
    PROXY_SETTLED = "PROXY_SETTLED"
    PLACED_AMOUNT = "PLACED_AMOUNT"


class BidStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WON = "WON"
    LOST = "LOST"
    RETRACTED = "RETRACTED"


class PledgeStatus(str, Enum):
    PROMISED = "PROMISED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    LAPSED = "LAPSED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceLineType(str, Enum):
    AUCTION_ITEM = "AUCTION_ITEM"
    TICKET = "TICKET"
    PADDLE_RAISE = "PADDLE_RAISE"
    PROCESSING_FEE = "PROCESSING_FEE"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    CHECK = "CHECK"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"


class RevenueBasis(str, Enum):
    BOOKED = "BOOKED"
    CASH_BASIS = "CASH_BASIS"


class ReconciliationRunStatus(str, Enum):
    PREPARED = "PREPARED"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class RevenueChannel(str, Enum):
    TICKETS = "TICKETS"
    AUCTION = "AUCTION"
    PADDLE = "PADDLE"
    PLEDGE = "PLEDGE"
    SPONSORSHIP = "SPONSORSHIP"


# ─── Entity shapes ──────────────────────────────────────────────────────────

class GalaEvent(TypedDict):
    id: str
    name: str
    event_start_utc: str
    event_end_utc: str
    match_cap_cents: int
    status: str
    posture: str
    match_awarded_cents: int
    gross_collected_cents: int
    open_lot_count: int
    unpaid_invoice_count: int
    created_at: str
    updated_at: str
    version: int


class TicketTable(TypedDict):
    id: str
    event_id: str
    table_name: str
    seat_count: int
    table_price_cents: int
    seat_price_cents: int
    seats_reserved: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TableHold(TypedDict):
    id: str
    table_id: str
    bidder_id: str
    hold_start_utc: str
    hold_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TicketOrder(TypedDict):
    id: str
    event_id: str
    bidder_id: str
    table_id: str
    order_type: str
    seat_count: int
    unit_price_cents: int
    subtotal_cents: int
    benefit_value_cents: int
    early_bird_applied: bool
    payment_status: str
    seating_status: str
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bidder(TypedDict):
    id: str
    event_id: str
    display_name: str
    email: str
    paddle_number: int
    payment_method_on_file: bool
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    event_id: str
    org_name: str
    tier: str
    commitment_cents: int
    paid_amount_cents: int
    placed_ad_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramAd(TypedDict):
    id: str
    sponsor_id: str
    event_id: str
    ad_size: str
    artwork_ref: str
    revision_count: int
    page_number: Optional[int]
    review_notes: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionItem(TypedDict):
    id: str
    event_id: str
    title: str
    item_type: str
    starting_bid_cents: int
    min_increment_cents: int
    estimated_fmv_cents: int
    open_at_utc: str
    close_at_utc: str
    live_lot_sequence: Optional[int]
    listing_status: str
    settlement_status: str
    current_leading_amount_cents: int
    hammer_price_cents: Optional[int]
    winning_bid_id: Optional[str]
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    item_id: str
    bidder_id: str
    amount_cents: int
    proxy_max_cents: int
    effective_max_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaddleRaise(TypedDict):
    id: str
    event_id: str
    bidder_id: str
    level_cents: int
    match_cents: int
    settlement_status: str
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pledge(TypedDict):
    id: str
    event_id: str
    bidder_id: str
    total_amount_cents: int
    installment_count: int
    first_due_utc: str
    received_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    line_type: str
    source_id: Optional[str]
    amount_cents: int


class CheckoutInvoice(TypedDict):
    id: str
    event_id: str
    bidder_id: str
    cover_processing_fee: bool
    line_items: List[InvoiceLine]
    line_subtotal_cents: int
    processing_fee_cents: int
    total_due_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentTransaction(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    status: str
    captured_by_user_id: str
    voided_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict):
    id: str
    invoice_id: str
    bidder_id: str
    issued_at_utc: str
    total_paid_cents: int
    benefit_value_cents: int
    tax_deductible_cents: int
    created_at: str
    updated_at: str
    version: int


class ChannelBreakdownEntry(TypedDict):
    channel: str
    expected_cents: int


class ReconciliationRun(TypedDict):
    id: str
    event_id: str
    revenue_basis: str
    prepared_by_user_id: str
    finalized_by_user_id: Optional[str]
    channel_breakdown: List[ChannelBreakdownEntry]
    expected_total_cents: int
    collected_total_cents: int
    variance_cents: int
    is_material_variance: bool
    variance_override_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
