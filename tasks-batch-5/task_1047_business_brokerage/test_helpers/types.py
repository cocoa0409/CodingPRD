"""Domain types: entity TypedDicts, status enums, role enum for the Business Brokerage API."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BROKER = "Broker"
    SELLER = "Seller"
    BUYER = "Buyer"
    LENDER = "Lender"
    ESCROW_AGENT = "EscrowAgent"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_LOI = "UNDER_LOI"
    IN_ESCROW = "IN_ESCROW"
    SOLD = "SOLD"
    WITHDRAWN = "WITHDRAWN"


class CIMStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class NDAStatus(str, Enum):
    SIGNED = "SIGNED"


class MeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"


class DealStatus(str, Enum):
    PROSPECT = "PROSPECT"
    QUALIFIED = "QUALIFIED"
    UNDER_LOI = "UNDER_LOI"
    DUE_DILIGENCE = "DUE_DILIGENCE"
    FINANCING = "FINANCING"
    IN_ESCROW = "IN_ESCROW"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class LOIStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class LoanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    CONDITIONALLY_APPROVED = "CONDITIONALLY_APPROVED"
    DECLINED = "DECLINED"


class EscrowStatus(str, Enum):
    OPENED = "OPENED"
    FUNDED = "FUNDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ValuationMethod(str, Enum):
    SDE_MULTIPLE = "SDE_MULTIPLE"
    ASSET_BASED = "ASSET_BASED"


class DocType(str, Enum):
    FINANCIALS = "FINANCIALS"
    LEASE = "LEASE"
    TAX_RETURN = "TAX_RETURN"
    LICENSES = "LICENSES"
    OTHER = "OTHER"


# All entities carry the full audit set: id, created_at, updated_at, version.

class Broker(TypedDict):
    id: str
    firm_name: str
    license_number: str
    accrued_commission_cents: int
    created_at: str
    updated_at: str
    version: int


class Seller(TypedDict):
    id: str
    full_name: str
    email: str
    created_at: str
    updated_at: str
    version: int


class Buyer(TypedDict):
    id: str
    full_name: str
    email: str
    proof_of_funds_cents: int
    net_worth_cents: int
    committed_capital_cents: int
    escrowed_cents: int
    available_capital_cents: int
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    broker_id: str
    seller_id: str
    business_name: str
    industry_code: str
    annual_sde_cents: int
    annual_revenue_cents: int
    ffe_value_cents: int
    inventory_value_cents: int
    industry_multiple: float
    asking_price_cents: int
    exclusive_start_date: str
    exclusive_end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CIM(TypedDict):
    id: str
    listing_id: str
    valuation_method: str
    recommended_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class NDA(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DataRoomDocument(TypedDict):
    id: str
    listing_id: str
    title: str
    doc_type: str
    created_at: str
    updated_at: str
    version: int


class ManagementMeeting(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    broker_id: str
    status: str
    accepted_loi_id: Optional[str]
    accepted_price_cents: Optional[int]
    earnout_total_cents: int
    earnout_periods: int
    earnout_baseline_sde_cents: int
    earnout_paid_cents: int
    provisional_commission_cents: Optional[int]
    final_commission_cents: Optional[int]
    seller_net_proceeds_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class LOI(TypedDict):
    id: str
    deal_id: str
    offer_price_cents: int
    earnest_deposit_cents: int
    earnout_amount_cents: int
    earnout_periods: int
    financing_contingency: bool
    counter_price_cents: Optional[int]
    round_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SBALoanApplication(TypedDict):
    id: str
    deal_id: str
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    decision_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EscrowAccount(TypedDict):
    id: str
    deal_id: str
    closing_price_cents: int
    required_deposit_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
