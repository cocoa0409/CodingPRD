"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SELLER = "Seller"
    BROKER_AGENT = "BrokerAgent"
    BUYER = "Buyer"
    PLATFORM_ADMIN = "PlatformAdmin"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    PACKAGED = "PACKAGED"
    MARKETED = "MARKETED"
    AUCTION_SCHEDULED = "AUCTION_SCHEDULED"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class PackagingStrategy(str, Enum):
    WHOLE = "WHOLE"
    SPLIT = "SPLIT"
    COMBINATION = "COMBINATION"


class TractStatus(str, Enum):
    REGISTERED = "REGISTERED"
    OFFERED = "OFFERED"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"
    WITHDRAWN = "WITHDRAWN"


class AuctionMethod(str, Enum):
    LIVE = "LIVE"
    ONLINE = "ONLINE"
    SEALED_BID = "SEALED_BID"


class AuctionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    EXTENDED = "EXTENDED"
    CLOSED_PENDING_AWARD = "CLOSED_PENDING_AWARD"
    AWARDED = "AWARDED"
    NO_SALE = "NO_SALE"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    PLACED = "PLACED"
    SEALED = "SEALED"
    REVEALED = "REVEALED"
    OUTBID = "OUTBID"
    LOST = "LOST"
    CONFIRMED_WINNER = "CONFIRMED_WINNER"
    VOIDED = "VOIDED"


class BuyerQualificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    QUALIFIED = "QUALIFIED"
    EXPIRED = "EXPIRED"
    DISQUALIFIED = "DISQUALIFIED"


class DepositStatus(str, Enum):
    PENDING = "PENDING"
    RECEIVED = "RECEIVED"
    LATE = "LATE"
    VERIFIED = "VERIFIED"
    FORFEITED = "FORFEITED"
    REFUNDED = "REFUNDED"
    APPLIED_TO_CLOSING = "APPLIED_TO_CLOSING"


class DisclosureStatus(str, Enum):
    DISCLOSED = "DISCLOSED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    POSSESSION_TRANSFERRED = "POSSESSION_TRANSFERRED"


class RightsStatus(str, Enum):
    DECLARED = "DECLARED"
    LOCKED = "LOCKED"


class MineralRights(str, Enum):
    CONVEYED = "CONVEYED"
    RESERVED = "RESERVED"
    PARTIALLY_CONVEYED = "PARTIALLY_CONVEYED"


class WindRights(str, Enum):
    CONVEYED = "CONVEYED"
    RESERVED = "RESERVED"
    LEASED_TO_THIRD_PARTY = "LEASED_TO_THIRD_PARTY"


class TitleStatus(str, Enum):
    NOT_ORDERED = "NOT_ORDERED"
    ORDERED = "ORDERED"
    COMMITMENT_RECEIVED = "COMMITMENT_RECEIVED"
    EXCEPTION_RAISED = "EXCEPTION_RAISED"
    CLEARED = "CLEARED"


class SurveyStatus(str, Enum):
    NOT_ORDERED = "NOT_ORDERED"
    ORDERED = "ORDERED"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


class FundingStatus(str, Enum):
    UNFUNDED = "UNFUNDED"
    FUNDS_RECEIVED = "FUNDS_RECEIVED"
    DISBURSED = "DISBURSED"


class ClosingOverallStatus(str, Enum):
    INITIATED = "INITIATED"
    COORDINATION = "COORDINATION"
    READY_TO_CLOSE = "READY_TO_CLOSE"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class StatementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    SUPERSEDED = "SUPERSEDED"
    FINAL = "FINAL"
    PAID = "PAID"


# --- Entity TypedDicts (common fields per PRD §2.4) ---


class Seller(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class BrokerAgent(TypedDict):
    id: str
    full_name: str
    license_number: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    full_name: str
    email: str
    proof_of_funds_amount: float
    qualification_status: str
    qualification_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    seller_id: str
    agent_id: str
    title: str
    county: str
    state_code: str
    total_gross_acres: float
    packaging_strategy: str
    reserve_price_total: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Tract(TypedDict):
    id: str
    listing_id: str
    tract_number: int
    gross_acres: float
    tillable_acres: float
    soil_productivity_index: float
    min_price: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ComparableSale(TypedDict):
    """Immutable record: carries only id + created_at (PRD §2.4)."""

    id: str
    county: str
    state_code: str
    sale_date: str
    sale_price_total: float
    gross_acres: float
    tillable_acres: float
    soil_productivity_index: float
    created_at: str


class AuctionEvent(TypedDict):
    id: str
    listing_id: str
    agent_id: str
    method: str
    scheduled_start: str
    scheduled_end: str
    soft_close_window_minutes: int
    extension_minutes: int
    effective_end: str
    extension_count: int
    awarded_total: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    auction_id: str
    buyer_id: str
    amount: Optional[float]  # null while SEALED (PRD §3.6)
    tract_ids: list
    status: str
    created_at: str
    updated_at: str
    version: int


class EarnestMoneyDeposit(TypedDict):
    id: str
    bid_id: str
    buyer_id: str
    amount_due: float
    amount_received: float
    due_at: str
    amount_refunded: float
    amount_forfeited: float
    amount_applied: float
    status: str
    created_at: str
    updated_at: str
    version: int


class LeaseDisclosure(TypedDict):
    id: str
    tract_id: str
    tenant_name: str
    lease_start_date: str
    lease_end_date: str
    annual_rent: float
    acknowledged_by_buyer_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RightsDisposition(TypedDict):
    id: str
    tract_id: str
    mineral_rights: str
    wind_rights: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClosingPackage(TypedDict):
    id: str
    auction_id: str
    target_closing_date: str
    payoff_amount: float
    title_status: str
    survey_status: str
    funding_status: str
    overall_status: str
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict):
    id: str
    closing_id: str
    variant: str
    gross_price: float
    commission_amount: float
    allocated_seller_costs: float
    tract_allocations: Optional[list]
    payoff_amount: float
    rent_credit: float
    seller_net: float
    status: str
    created_at: str
    updated_at: str
    version: int
