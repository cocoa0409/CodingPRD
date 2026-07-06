"""Domain types: entity TypedDicts, status enums, role enum for the Estate Sale API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SALE_MANAGER = "SaleManager"
    APPRAISER = "Appraiser"
    CASHIER = "Cashier"
    CLIENT = "Client"


class ProjectStatus(str, Enum):
    LEAD = "LEAD"
    ASSESSED = "ASSESSED"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    CONTRACTED = "CONTRACTED"
    SALE_SETUP = "SALE_SETUP"
    SALE_LIVE = "SALE_LIVE"
    SETTLING = "SETTLING"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    NEW = "NEW"
    RESEARCHED = "RESEARCHED"
    PRICED = "PRICED"
    STAGED = "STAGED"
    TAGGED = "TAGGED"
    LISTED = "LISTED"
    BID_CLOSED = "BID_CLOSED"
    SOLD = "SOLD"
    UNSOLD = "UNSOLD"
    WITHDRAWN = "WITHDRAWN"


class SaleEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TransactionStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class BidStatus(str, Enum):
    PLACED = "PLACED"
    WON = "WON"
    LOST = "LOST"
    VOIDED = "VOIDED"


class HaulJobStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class HandlingType(str, Enum):
    CONSIGNMENT = "CONSIGNMENT"
    BUYOUT = "BUYOUT"


class BidMode(str, Enum):
    FIRST_PRICE = "FIRST_PRICE"
    SECOND_PRICE = "SECOND_PRICE"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"


class DispositionType(str, Enum):
    DONATION = "DONATION"
    HAULAWAY = "HAULAWAY"
    BUYBACK = "BUYBACK"


# All entities carry the standard system fields: id, created_at, updated_at, version.

class Client(TypedDict):
    id: str
    name: str
    phone: str
    email: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    client_id: str
    address: str
    estimated_total_value_cents: int
    minimum_commission_cents: int
    assessment_notes: Optional[str]
    status: str
    gross_sales_cents: int
    buyout_advances_cents: int
    unsold_lot_count: int
    estimated_gross_consignment_cents: int
    estimated_commission_cents: int
    estimated_net_to_client_cents: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    project_id: str
    title: str
    handling_type: str
    is_bid_lot: bool
    bid_mode: Optional[str]
    list_price_cents: Optional[int]
    reserve_price_cents: Optional[int]
    min_increment_cents: Optional[int]
    research_notes: Optional[str]
    researched_by_user_id: Optional[str]
    approved_buyout_by_user_id: Optional[str]
    buyout_price_cents: Optional[int]
    winning_bid_id: Optional[str]
    winning_bid_price_cents: Optional[int]
    final_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SaleEvent(TypedDict):
    id: str
    project_id: str
    crew_id: str
    start_at: str
    end_at: str
    markdown_day1_pct: float
    markdown_day2_pct: float
    markdown_day3plus_pct: float
    window_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    name: str
    booked_minutes: int
    created_at: str
    updated_at: str
    version: int


class Transaction(TypedDict):
    id: str
    sale_event_id: str
    lot_id: str
    payment_method: str
    buyer_name: Optional[str]
    final_price_cents: int
    card_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    lot_id: str
    amount_cents: int
    bidder_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HaulJob(TypedDict):
    id: str
    project_id: str
    truck_id: str
    disposition_type: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class SettlementStatement(TypedDict):
    id: str
    project_id: str
    gross_consignment_cents: int
    commission_cents: int
    card_fees_cents: int
    buyout_advances_cents: int
    net_to_client_cents: int
    unsold_lot_count: int
    superseded: bool
    created_at: str
    updated_at: str
    version: int
