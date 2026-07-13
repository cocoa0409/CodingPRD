"""Domain types: entity TypedDicts, status enums, role enum.

Types for the Estate-Liquidation Auction API. Append-only records
(Photo, Bid, Payment, Donation) carry only id + created_at — no
updated_at, no version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    OPERATOR = "Operator"
    BUYER = "Buyer"
    ANONYMOUS = "Anonymous"


class EstateStatus(str, Enum):
    CATALOGING = "CATALOGING"
    LIVE = "LIVE"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"
    CLEANED_OUT = "CLEANED_OUT"


class LotStatus(str, Enum):
    DRAFT = "DRAFT"
    CATALOGED = "CATALOGED"
    LISTED = "LISTED"
    SELLING = "SELLING"
    SOLD = "SOLD"
    PASSED = "PASSED"
    DONATED = "DONATED"
    WITHDRAWN = "WITHDRAWN"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class BuyerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VERIFIED = "VERIFIED"
    SUSPENDED = "SUSPENDED"


class BidStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    OUTBID = "OUTBID"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class OrderPickupStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    PICKED_UP = "PICKED_UP"
    NO_SHOW = "NO_SHOW"


class PaymentKind(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class DisputeOutcome(str, Enum):
    BUYER_FAVOR = "BUYER_FAVOR"
    SELLER_FAVOR = "SELLER_FAVOR"


class DonationDisposition(str, Enum):
    DONATED = "DONATED"
    RECYCLED = "RECYCLED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
class Estate(TypedDict):
    id: str
    seller_name: str
    seller_email: str
    commission_bps: int
    buyer_premium_bps: int
    auction_starts_at: str
    auction_ends_at: str
    soft_close_seconds: int
    extended_count: int
    status: str
    lot_count: int
    provisional_gross_cents: int
    gross_sales_cents: int
    commission_cents: int
    seller_payout_cents: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    estate_id: str
    title: str
    description: str
    category: str
    condition_grade: str
    starting_bid_cents: int
    reserve_cents: Optional[int]
    current_bid_cents: int
    high_bidder_id: Optional[str]
    bid_count: int
    photo_count: int
    hammer_price_cents: Optional[int]
    winning_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only condition record: id + created_at only.
class Photo(TypedDict):
    id: str
    lot_id: str
    image_url: str
    caption: Optional[str]
    condition_note: Optional[str]
    is_primary: bool
    created_at: str


class Buyer(TypedDict):
    id: str
    display_name: str
    email: str
    status: str
    no_show_strikes: int
    gross_owed_cents: int
    net_owed_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only bid record: id + created_at only.
class Bid(TypedDict):
    id: str
    lot_id: str
    buyer_id: str
    amount_cents: int
    expected_lot_version: int
    status: str
    is_winning: bool
    created_at: str


class Order(TypedDict):
    id: str
    estate_id: str
    buyer_id: str
    lot_ids: List[str]
    subtotal_cents: int
    buyer_premium_cents: int
    sales_tax_cents: int
    total_cents: int
    amount_paid_cents: int
    payment_status: str
    pickup_status: str
    pickup_window_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only ledger line: id + created_at only.
class Payment(TypedDict):
    id: str
    order_id: str
    kind: str
    amount_cents: int
    note: Optional[str]
    created_at: str


class PickupWindow(TypedDict):
    id: str
    estate_id: str
    starts_at: str
    ends_at: str
    capacity: int
    booked_count: int
    label: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    order_id: str
    lot_id: str
    reason: str
    status: str
    outcome: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only disposal record: id + created_at only.
class Donation(TypedDict):
    id: str
    lot_id: str
    estate_id: str
    recipient: str
    disposition: str
    created_at: str
