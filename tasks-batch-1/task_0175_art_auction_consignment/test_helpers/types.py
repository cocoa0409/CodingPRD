"""Domain types for the Art Auction Consignment API: entity TypedDicts,
status enums, and the role enum.

Two entities carry only id + created_at (no updated_at, no version): a
PremiumSchedule is immutable after creation (PRD §2.4). Every other entity
carries the full id/created_at/updated_at/version set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SALE_ADMINISTRATOR = "SaleAdministrator"
    AUCTIONEER = "Auctioneer"
    FINANCE_OFFICER = "FinanceOfficer"
    SELLER = "Seller"
    BIDDER = "Bidder"
    VIEWER = "Viewer"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class BidderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AuctionSaleStatus(str, Enum):
    CATALOGING = "CATALOGING"
    PUBLISHED = "PUBLISHED"
    LIVE = "LIVE"
    CLOSED = "CLOSED"


class ConsignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class LotSaleStatus(str, Enum):
    CATALOGED = "CATALOGED"
    OPEN = "OPEN"
    SOLD = "SOLD"
    BOUGHT_IN = "BOUGHT_IN"
    WITHDRAWN = "WITHDRAWN"


class LotSettlementStatus(str, Enum):
    NONE = "NONE"
    INVOICED = "INVOICED"
    STATEMENTED = "STATEMENTED"
    SETTLED = "SETTLED"


class PaddleRegistrationType(str, Enum):
    FLOOR = "FLOOR"
    ABSENTEE = "ABSENTEE"
    PHONE = "PHONE"


class PaddleRegistrationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class BidChannel(str, Enum):
    FLOOR = "FLOOR"
    ABSENTEE = "ABSENTEE"
    PHONE = "PHONE"


class BidStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    RETRACTED = "RETRACTED"
    WINNING = "WINNING"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class ResaleRoyaltyStatus(str, Enum):
    ACCRUED = "ACCRUED"
    REMITTED = "REMITTED"
    REVERSED = "REVERSED"


class ResaleRoyaltyBearer(str, Enum):
    SELLER = "SELLER"


class SellerStatementStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REVERSED = "REVERSED"


class PayoutStatus(str, Enum):
    DISBURSED = "DISBURSED"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------
class Seller(TypedDict):
    id: str
    legal_name: str
    email: str
    country_code: str
    payout_iban: str
    created_at: str
    updated_at: str
    version: int


class Bidder(TypedDict):
    id: str
    legal_name: str
    email: str
    country_code: str
    credit_limit_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AuctionSale(TypedDict):
    id: str
    title: str
    sale_date_utc: str
    currency: str
    buyers_premium_schedule_id: str
    status: str
    lot_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable, carries ONLY id + created_at
class PremiumSchedule(TypedDict):
    id: str
    created_at: str
    name: str
    tiers: List[dict]


class Consignment(TypedDict):
    id: str
    seller_id: str
    seller_commission_bps: int
    unsold_fee_cents: int
    status: str
    lot_count: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    auction_sale_id: str
    consignment_id: str
    lot_number: int
    title: str
    artist_name: str
    artist_alive: bool
    low_estimate_cents: int
    high_estimate_cents: int
    reserve_cents: int
    hammer_price_cents: int
    winning_paddle_registration_id: Optional[str]
    sale_status: str
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class PaddleRegistration(TypedDict):
    id: str
    auction_sale_id: str
    bidder_id: str
    paddle_number: int
    registration_type: str
    max_absentee_bid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    lot_id: str
    paddle_registration_id: str
    amount_cents: int
    bid_channel: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    lot_id: str
    paddle_registration_id: str
    bidder_id: str
    hammer_price_cents: int
    buyers_premium_cents: int
    total_due_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ResaleRoyalty(TypedDict):
    id: str
    lot_id: str
    hammer_price_cents: int
    royalty_cents: int
    bearer: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SellerStatement(TypedDict):
    id: str
    lot_id: str
    consignment_id: str
    hammer_price_cents: int
    seller_commission_cents: int
    resale_royalty_withheld_cents: int
    net_payable_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    seller_statement_id: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
