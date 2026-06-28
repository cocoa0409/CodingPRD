"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the full common-field set (id, created_at,
updated_at, version) per PRD §2.5.
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    COUNTY_TREASURER = "CountyTreasurer"
    INVESTOR = "Investor"
    AUDITOR = "Auditor"


class ParcelStatus(str, Enum):
    DELINQUENT = "DELINQUENT"
    ON_SALE = "ON_SALE"
    LIENED = "LIENED"
    REDEEMED = "REDEEMED"
    DEEDED = "DEEDED"


class TaxSaleStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class SaleType(str, Enum):
    RATE_BID_DOWN = "RATE_BID_DOWN"
    PREMIUM = "PREMIUM"


class SaleListingStatus(str, Enum):
    LISTED = "LISTED"
    SOLD = "SOLD"
    STRUCK_OFF = "STRUCK_OFF"
    WITHDRAWN = "WITHDRAWN"


class BidStatus(str, Enum):
    PLACED = "PLACED"
    WON = "WON"
    LOST = "LOST"
    REFUNDED = "REFUNDED"


class CertificateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FORECLOSURE_PENDING = "FORECLOSURE_PENDING"
    REDEEMED = "REDEEMED"
    DEEDED = "DEEDED"


class SubsequentTaxStatus(str, Enum):
    POSTED = "POSTED"
    REDEEMED = "REDEEMED"


class AssignmentStatus(str, Enum):
    RECORDED = "RECORDED"


class DeedApplicationStatus(str, Enum):
    FILED = "FILED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (all common_fields: true) ---

class County(TypedDict):
    id: str
    name: str
    state_code: str
    max_interest_rate_bps: int
    bid_down_increment_bps: int
    redemption_period_days: int
    penalty_rate_bps: int
    sub_tax_interest_rate_bps: int
    premium_bidding_enabled: bool
    premium_earns_interest: bool
    day_count_basis: int
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    county_id: str
    apn: str
    owner_name: str
    assessed_value_cents: int
    base_tax_due_cents: int
    status: str
    active_certificate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Investor(TypedDict):
    id: str
    legal_name: str
    tax_id: str
    escrow_balance_cents: int
    deposit_total_cents: int
    registered: bool
    created_at: str
    updated_at: str
    version: int


class TaxSale(TypedDict):
    id: str
    county_id: str
    sale_name: str
    sale_type: str
    scheduled_at: str
    status: str
    listing_count: int
    created_at: str
    updated_at: str
    version: int


class SaleListing(TypedDict):
    id: str
    sale_id: str
    parcel_id: str
    opening_rate_bps: int
    status: str
    winning_bid_id: Optional[str]
    certificate_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict):
    id: str
    listing_id: str
    investor_id: str
    rate_bps: Optional[int]
    premium_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict):
    id: str
    county_id: str
    parcel_id: str
    listing_id: str
    holder_investor_id: str
    face_amount_cents: int
    rate_bps: int
    premium_cents: int
    issued_at: str
    redeem_deadline_at: str
    sub_tax_total_cents: int
    assignment_seq: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SubsequentTax(TypedDict):
    id: str
    certificate_id: str
    investor_id: str
    tax_year: int
    principal_cents: int
    posted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Redemption(TypedDict):
    id: str
    certificate_id: str
    redeemed_at: str
    face_payoff_cents: int
    face_interest_cents: int
    penalty_cents: int
    sub_tax_payoff_cents: int
    sub_tax_interest_cents: int
    premium_refund_cents: int
    total_payoff_cents: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    certificate_id: str
    from_investor_id: str
    to_investor_id: str
    consideration_cents: int
    seq: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeedApplication(TypedDict):
    id: str
    certificate_id: str
    applicant_investor_id: str
    deed_cost_cents: int
    minimum_bid_cents: int
    sale_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurplusDistribution(TypedDict):
    id: str
    deed_application_id: str
    certificate_id: str
    gross_proceeds_cents: int
    lien_satisfied_cents: int
    surplus_cents: int
    claimed: bool
    created_at: str
    updated_at: str
    version: int
