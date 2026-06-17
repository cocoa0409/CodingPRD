"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Roles ──────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    AUCTION_ADMIN = "AuctionAdmin"
    SELLER = "Seller"
    BUYER = "Buyer"
    ARBITRATOR = "Arbitrator"


# ─── Status enums ───────────────────────────────────────────────────────
class SaleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    RUNNING = "RUNNING"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class LaneStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class SellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BuyerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ConsignmentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CATALOGED = "CATALOGED"
    RUN_LISTED = "RUN_LISTED"
    SOLD = "SOLD"
    NO_SALE = "NO_SALE"
    IF_PENDING = "IF_PENDING"
    SETTLED = "SETTLED"
    ARB_UNWOUND = "ARB_UNWOUND"
    WITHDRAWN = "WITHDRAWN"


class LotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    BIDDING_OPEN = "BIDDING_OPEN"
    BIDDING_CLOSED = "BIDDING_CLOSED"
    HAMMERED = "HAMMERED"
    PASSED = "PASSED"
    IF_PENDING = "IF_PENDING"
    FINALIZED = "FINALIZED"
    ARB_REVERSED = "ARB_REVERSED"
    WITHDRAWN = "WITHDRAWN"


class LotOutcome(str, Enum):
    NONE = "NONE"
    SOLD = "SOLD"
    IF = "IF"
    PASSED = "PASSED"


class BidType(str, Enum):
    LIVE = "LIVE"
    PROXY = "PROXY"


class BidChannel(str, Enum):
    LANE = "LANE"
    ONLINE = "ONLINE"


class ClaimResolution(str, Enum):
    PENDING = "PENDING"
    APPROVED_FULL = "APPROVED_FULL"
    APPROVED_PARTIAL = "APPROVED_PARTIAL"
    DENIED = "DENIED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REVERSED = "REVERSED"
    WRITTEN_OFF = "WRITTEN_OFF"


class TitleStatus(str, Enum):
    PENDING_TITLE = "PENDING_TITLE"
    TITLE_RECEIVED = "TITLE_RECEIVED"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    VOID = "VOID"
    DEFAULTED = "DEFAULTED"


class GatePassStatus(str, Enum):
    ISSUED = "ISSUED"
    REDEEMED = "REDEEMED"
    VOID = "VOID"


class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TransportStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ConsignmentTitleStatus(str, Enum):
    ABSENT = "ABSENT"
    ON_HAND = "ON_HAND"


# ─── Entity TypedDicts (common_fields: true unless noted) ───────────────
class AuctionSale(TypedDict):
    id: str
    sale_name: str
    sale_date: str
    buyer_fee_schedule_code: str
    status: str
    lane_count: int
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict):
    id: str
    sale_id: str
    lane_number: int
    open_minute: int
    close_minute: int
    scheduled_slot_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Seller(TypedDict):
    id: str
    dealer_name: str
    seller_fee_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    dealer_name: str
    credit_limit_cents: int
    committed_cents: int
    available_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict):
    id: str
    sale_id: str
    seller_id: str
    vin: str
    reserve_price_cents: int
    floor_price_cents: int
    title_status: str
    expected_proceeds_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConditionReport(TypedDict):
    id: str
    consignment_id: str
    grade: float
    odometer_miles: int
    announcements: List[str]
    as_is: bool
    created_at: str
    updated_at: str
    version: int


class RunListEntry(TypedDict):
    id: str
    sale_id: str
    consignment_id: str
    lane_id: str
    run_number: int
    slot_start_minute: int
    slot_end_minute: int
    starting_bid_cents: int
    high_bid_cents: int
    high_bidder_id: Optional[str]
    hammer_price_cents: int
    outcome: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Bid — common_fields: false → append-only event: only id + created_at
class Bid(TypedDict):
    id: str
    lot_id: str
    buyer_id: str
    bid_type: str
    channel: str
    amount_cents: int
    ceiling_cents: int
    created_at: str


class ArbitrationClaim(TypedDict):
    id: str
    lot_id: str
    buyer_id: str
    reason_code: str
    claimed_cents: int
    approved_cents: int
    resolution: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    lot_id: str
    buyer_id: str
    seller_id: str
    sale_price_cents: int
    buyer_fee_cents: int
    total_due_cents: int
    seller_proceeds_cents: int
    payment_status: str
    title_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GatePass(TypedDict):
    id: str
    settlement_id: str
    buyer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict):
    id: str
    carrier_name: str
    turnaround_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransportOrder(TypedDict):
    id: str
    settlement_id: str
    carrier_id: str
    pickup_start_minute: int
    pickup_end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int
