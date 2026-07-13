"""Domain types: entity TypedDicts, status enums, role enum.

Every persisted resource carries the common system fields id, created_at,
updated_at, and version (see PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FACILITY_OPERATOR = "FacilityOperator"
    BUYER = "Buyer"
    TENANT = "Tenant"


class UnitStatus(str, Enum):
    RENTED = "RENTED"
    LIEN_NOTICED = "LIEN_NOTICED"
    LIEN_MATURED = "LIEN_MATURED"
    IN_AUCTION = "IN_AUCTION"
    SOLD = "SOLD"
    CLEARED = "CLEARED"


class LienNoticeStatus(str, Enum):
    SENT = "SENT"
    CURED = "CURED"
    MATURED = "MATURED"
    WITHDRAWN = "WITHDRAWN"


class AuctionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    SETTLED = "SETTLED"


class AuctionMode(str, Enum):
    ONLINE = "ONLINE"
    ONSITE = "ONSITE"


class BidStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUTBID = "OUTBID"
    WINNING = "WINNING"
    LOST = "LOST"
    RETRACTED = "RETRACTED"


class BuyerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    SUSPENDED = "SUSPENDED"


class TenantAccessStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class CleanoutStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    OVERDUE = "OVERDUE"
    VOIDED = "VOIDED"


class SettlementStatus(str, Enum):
    FINALIZED = "FINALIZED"
    REVERSED = "REVERSED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class DisputeResolution(str, Enum):
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class Facility(TypedDict):
    id: str
    name: str
    state_code: str
    sales_tax_rate_bps: int
    facility_fee_bps: int
    recovery_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    facility_id: str
    full_name: str
    email: str
    access_status: str
    surplus_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class StorageUnit(TypedDict):
    id: str
    facility_id: str
    tenant_id: str
    unit_number: str
    monthly_rent_cents: int
    past_due_balance_cents: int
    status: str
    lien_amount_provisional_cents: int
    lien_amount_final_cents: int
    created_at: str
    updated_at: str
    version: int


class LienNotice(TypedDict):
    id: str
    unit_id: str
    notice_sent_at: str
    cure_deadline: str
    lien_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Auction(TypedDict):
    id: str
    unit_id: str
    mode: str
    start_at: str
    end_at: str
    reserve_cents: int
    min_increment_cents: int
    high_bid_cents: int
    high_bid_id: Optional[str]
    min_next_bid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    full_name: str
    email: str
    status: str
    deposit_available_cents: int
    deposit_held_cents: int
    deposit_forfeited_cents: int
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    auction_id: str
    buyer_id: str
    amount_cents: int
    placed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Sale(TypedDict):
    id: str
    auction_id: str
    buyer_id: str
    winning_amount_cents: int
    buyer_premium_cents: int
    sales_tax_cents: int
    total_due_cents: int
    estimated_surplus_cents: int
    payment_deadline: str
    cleanout_deadline: str
    payment_status: str
    cleanout_status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    sale_id: str
    gross_proceeds_cents: int
    lien_recovered_cents: int
    facility_fee_cents: int
    surplus_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    subject_type: str
    sale_id: Optional[str]
    settlement_id: Optional[str]
    raised_by: str
    reason: str
    resolution: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
