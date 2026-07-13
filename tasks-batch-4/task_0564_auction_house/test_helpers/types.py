"""Domain types: entity TypedDicts, status enums, and the role enum.

All types are derived from the Auction House PRD (§2.4 common resource
properties, §3 workflows). Every primary resource carries id, created_at,
updated_at, and an integer version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ──────────────────────────────────────────────────────────

class BidderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AuctionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ConsignmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPRAISED = "APPRAISED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"


class LotStatus(str, Enum):
    CATALOGED = "CATALOGED"
    OPEN = "OPEN"
    HAMMERED = "HAMMERED"
    PASSED = "PASSED"
    RESCINDED = "RESCINDED"


class BidStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUTBID = "OUTBID"
    WINNING = "WINNING"
    RETRACTED = "RETRACTED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"


class FulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    PICKED_UP = "PICKED_UP"
    SHIPPED = "SHIPPED"


class InvoiceLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    PAID = "PAID"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    AUCTION_STAFF = "AuctionStaff"
    APPRAISER = "Appraiser"
    SETTLEMENT_OFFICER = "SettlementOfficer"
    CONSIGNOR = "Consignor"
    BIDDER = "Bidder"


# ─── Entity TypedDicts (all carry id/created_at/updated_at/version) ─────────

class Consignor(TypedDict):
    id: str
    display_name: str
    email: str
    payout_method: str
    created_at: str
    updated_at: str
    version: int


class Bidder(TypedDict):
    id: str
    display_name: str
    email: str
    paddle_number: str
    deposit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Saleroom(TypedDict):
    id: str
    name: str
    location: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class Auction(TypedDict):
    id: str
    title: str
    sale_type: str
    saleroom_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict):
    id: str
    consignor_id: str
    commission_rate: float
    estimate_low_cents: int
    estimate_high_cents: int
    intake_window_start: str
    intake_window_end: str
    status: str
    appraised_low_cents: Optional[int]
    appraised_high_cents: Optional[int]
    appraisal_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    consignment_id: str
    auction_id: str
    title: str
    category: str
    reserve_cents: int
    starting_bid_cents: int
    estimate_low_cents: int
    estimate_high_cents: int
    lot_number: int
    sale_status: str
    current_high_bid_cents: int
    current_high_bid_id: Optional[str]
    hammer_price_cents: Optional[int]
    winning_bid_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    lot_id: str
    bidder_id: str
    bid_type: str
    amount_cents: int
    expected_lot_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    bidder_id: str
    auction_id: str
    hammer_subtotal_cents: int
    premium_subtotal_cents: int
    storage_fee_cents: int
    shipping_fee_cents: int
    total_due_cents: int
    amount_paid_cents: int
    total_refunded_cents: int
    payment_status: str
    fulfillment_status: str
    fulfillment_method: Optional[str]
    storage_start_at: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    id: str
    invoice_id: str
    lot_id: str
    hammer_price_cents: int
    buyers_premium_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    consignment_id: str
    gross_hammer_cents: int
    seller_commission_cents: int
    net_payout_cents: int
    lot_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    invoice_line_id: str
    bidder_id: str
    reason: str
    status: str
    resolution_notes: Optional[str]
    refund_cents: int
    created_at: str
    updated_at: str
    version: int
