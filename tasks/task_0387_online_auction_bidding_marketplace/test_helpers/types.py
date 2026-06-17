"""Domain types: entity TypedDicts, status enums, role enum.

All names mirror the PRD's exact field and status spellings.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum (PRD §2.1) ---
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    BUYER = "Buyer"
    SELLER = "Seller"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums ---
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class AccountStanding(str, Enum):
    GOOD = "GOOD"
    SUSPENDED = "SUSPENDED"


class ListingFormat(str, Enum):
    AUCTION = "AUCTION"
    BUY_NOW = "BUY_NOW"
    HYBRID = "HYBRID"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    ENDED_MET = "ENDED_MET"
    ENDED_RESERVE_NOT_MET = "ENDED_RESERVE_NOT_MET"
    ENDED_NO_BIDS = "ENDED_NO_BIDS"
    SOLD = "SOLD"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    OUTBID = "OUTBID"
    RETRACTED = "RETRACTED"


class OfferStatus(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class OfferActor(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"


class OrderSource(str, Enum):
    AUCTION_WIN = "AUCTION_WIN"
    BUY_NOW = "BUY_NOW"
    OFFER_ACCEPT = "OFFER_ACCEPT"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"


class FulfillmentStatus(str, Enum):
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class InvoiceSettlementStatus(str, Enum):
    INVOICED = "INVOICED"
    PAID = "PAID"
    CREDITED = "CREDITED"


class PaymentKind(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class FeedbackRole(str, Enum):
    BUYER = "BUYER"
    SELLER = "SELLER"


class FeedbackRating(str, Enum):
    POSITIVE = "POSITIVE"
    NEUTRAL = "NEUTRAL"
    NEGATIVE = "NEGATIVE"


class DisputeReason(str, Enum):
    ITEM_NOT_RECEIVED = "ITEM_NOT_RECEIVED"
    NOT_AS_DESCRIBED = "NOT_AS_DESCRIBED"
    DAMAGED = "DAMAGED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    SELLER_RESPONDED = "SELLER_RESPONDED"
    ESCALATED = "ESCALATED"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_NO_REFUND = "RESOLVED_NO_REFUND"
    CLOSED = "CLOSED"


# --- Entity TypedDicts ---
# Entities carrying common_fields: id + created_at + updated_at + version.

class Account(TypedDict):
    id: str
    email: str
    display_name: str
    roles: List[str]
    fee_balance_cents: int
    feedback_score: int
    standing: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    seller_account_id: str
    title: str
    format: str
    start_price_cents: Optional[int]
    buy_now_price_cents: Optional[int]
    reserve_price_cents: Optional[int]
    accepts_offers: bool
    scheduled_end_at: Optional[str]
    effective_end_at: Optional[str]
    highest_bid_id: Optional[str]
    current_price_cents: Optional[int]
    bid_count: int
    status: str
    winner_account_id: Optional[str]
    sold_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    listing_id: str
    bidder_account_id: str
    max_proxy_cents: int
    current_price_cents: int
    is_winning: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    listing_id: str
    buyer_account_id: str
    amount_cents: int
    round_no: int
    last_actor: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    listing_id: str
    buyer_account_id: str
    seller_account_id: str
    source: str
    item_price_cents: int
    shipping_cents: int
    total_cents: int
    payment_status: str
    fulfillment_status: str
    paid_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class SellerFeeInvoice(TypedDict):
    id: str
    order_id: str
    seller_account_id: str
    gross_item_cents: int
    fvf_rate_basis_points: int
    amount_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    order_id: str
    opener_account_id: str
    reason: str
    requested_amount_cents: int
    resolved_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Lighter entities (common_fields: false) — only id + created_at.

class Watch(TypedDict):
    id: str
    listing_id: str
    watcher_account_id: str
    active: bool
    created_at: str


class Payment(TypedDict):
    id: str
    order_id: str
    kind: str
    amount_cents: int
    created_at: str


class Feedback(TypedDict):
    id: str
    order_id: str
    rater_account_id: str
    ratee_account_id: str
    role: str
    rating: str
    comment: str
    created_at: str
