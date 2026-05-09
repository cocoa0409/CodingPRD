"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SELLER = "Seller"
    BIDDER = "Bidder"
    ARBITRATOR_OPS = "ArbitratorOps"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


class SellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class BidderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class LotCategory(str, Enum):
    ART = "ART"
    COLLECTIBLE = "COLLECTIBLE"
    ELECTRONICS = "ELECTRONICS"
    JEWELRY = "JEWELRY"
    REAL_ESTATE = "REAL_ESTATE"
    VEHICLE = "VEHICLE"


class LotCondition(str, Enum):
    NEW = "NEW"
    LIKE_NEW = "LIKE_NEW"
    USED_GOOD = "USED_GOOD"
    USED_FAIR = "USED_FAIR"
    FOR_PARTS = "FOR_PARTS"


class LotStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"
    REOFFERED = "REOFFERED"
    DEFAULTED = "DEFAULTED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"
    RELISTED = "RELISTED"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WINNING = "WINNING"
    OUTBID = "OUTBID"
    WITHDRAWN_BY_RISK = "WITHDRAWN_BY_RISK"


class BidSource(str, Enum):
    MANUAL = "MANUAL"
    PROXY = "PROXY"


class AutoBidProxyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class DepositStatus(str, Enum):
    HELD = "HELD"
    RELEASED = "RELEASED"
    FORFEITED = "FORFEITED"
    PARTIAL_REFUND = "PARTIAL_REFUND"


class DepositTerminalReason(str, Enum):
    LOSING_BIDDER = "LOSING_BIDDER"
    WINNER_PAID = "WINNER_PAID"
    WINNER_DEFAULT_REOFFER_FILLED = "WINNER_DEFAULT_REOFFER_FILLED"
    WINNER_DEFAULT_NO_REOFFER = "WINNER_DEFAULT_NO_REOFFER"
    BIDDER_RISK_WITHDRAWN = "BIDDER_RISK_WITHDRAWN"
    DISPUTE_REFUND = "DISPUTE_REFUND"


class InvoiceStatus(str, Enum):
    PENDING = "PENDING"
    ISSUED = "ISSUED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class DisputeFiledBy(str, Enum):
    BIDDER = "BIDDER"
    SELLER = "SELLER"


class DisputeStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_REFUND = "RESOLVED_REFUND"
    RESOLVED_RELIST = "RESOLVED_RELIST"
    RESOLVED_DENIED = "RESOLVED_DENIED"


class DisputeOutcome(str, Enum):
    REFUND = "REFUND"
    RELIST = "RELIST"
    DENIED = "DENIED"


class Seller(TypedDict, total=False):
    id: str
    display_name: str
    status: str
    total_lots_listed: int
    gross_proceeds_cents: int
    net_proceeds_cents: int
    created_at: str
    updated_at: str
    version: int


class Bidder(TypedDict, total=False):
    id: str
    display_name: str
    affiliated_seller_id: Optional[str]
    identity_verified: bool
    wallet_balance_cents: int
    held_deposit_cents: int
    status: str
    risk_score: float
    chronic_score: float
    acute_score: float
    shill_pattern_detected: bool
    account_takeover_alert: bool
    withdrawal_count: int
    dispute_loss_count: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    seller_id: str
    title: str
    category: str
    condition: str
    physical_item_serial: str
    reserve_price_cents: int
    starting_bid_cents: int
    scheduled_start_at: str
    scheduled_end_at: str
    effective_end_at: Optional[str]
    extension_count: int
    status: str
    current_price_cents: int
    current_winner_bid_id: Optional[str]
    current_winner_bidder_id: Optional[str]
    bid_count: int
    has_met_reserve: bool
    hammer_price_cents: Optional[int]
    winning_bidder_id: Optional[str]
    runner_up_bid_id: Optional[str]
    payment_deadline_at: Optional[str]
    hammer_at: Optional[str]
    delivered_at: Optional[str]
    relisted_from_lot_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    lot_id: str
    bidder_id: str
    amount_cents: int
    source: str
    proxy_id: Optional[str]
    status: str
    deposit_id: str
    placed_at: str
    triggered_extension: bool
    created_at: str


class AutoBidProxy(TypedDict, total=False):
    id: str
    lot_id: str
    bidder_id: str
    max_amount_cents: Optional[int]
    status: str
    last_executed_amount_cents: Optional[int]
    bids_emitted_count: int
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    bidder_id: str
    lot_id: str
    amount_cents: int
    status: str
    refund_amount_cents: int
    forfeit_amount_cents: int
    terminal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    lot_id: str
    buyer_id: str
    seller_id: str
    hammer_price_cents: int
    buyer_premium_cents: int
    seller_commission_cents: int
    buyer_total_cents: int
    seller_payout_cents: int
    platform_take_cents: int
    status: str
    paid_at: Optional[str]
    refund_amount_cents: int
    commission_reversal_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict):
    url: str
    kind: str


class Dispute(TypedDict, total=False):
    id: str
    lot_id: str
    invoice_id: str
    filed_by: str
    filer_user_id: str
    reason: str
    evidence: List[EvidenceItem]
    claimed_refund_amount_cents: int
    status: str
    resolution_outcome: Optional[str]
    resolution_refund_amount_cents: int
    arbitrator_user_id: Optional[str]
    filed_at: str
    review_started_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
