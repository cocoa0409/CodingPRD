"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Role enum (X-User-Role values) ---
class UserRole(str, Enum):
    BROKERAGE_ADMIN = "BrokerageAdmin"
    LISTING_BROKER = "ListingBroker"
    TENANT_BROKER = "TenantBroker"


# --- Status enums ---
class BrokerageSide(str, Enum):
    LISTING = "LISTING"
    TENANT_REP = "TENANT_REP"
    DUAL = "DUAL"


class BrokerRole(str, Enum):
    LISTING_BROKER = "LISTING_BROKER"
    TENANT_BROKER = "TENANT_BROKER"
    ADMIN = "ADMIN"


class BrokerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AssetClass(str, Enum):
    OFFICE = "OFFICE"
    RETAIL = "RETAIL"
    INDUSTRIAL = "INDUSTRIAL"
    FLEX = "FLEX"


class SpaceStatus(str, Enum):
    DRAFT = "DRAFT"
    AVAILABLE = "AVAILABLE"
    ON_HOLD = "ON_HOLD"
    UNDER_LOI = "UNDER_LOI"
    LEASED = "LEASED"
    OFF_MARKET = "OFF_MARKET"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_NEGOTIATION = "UNDER_NEGOTIATION"
    EXECUTED = "EXECUTED"
    WITHDRAWN = "WITHDRAWN"


class RequirementStatus(str, Enum):
    OPEN = "OPEN"
    TOURING = "TOURING"
    NEGOTIATING = "NEGOTIATING"
    PLACED = "PLACED"
    CLOSED_LOST = "CLOSED_LOST"


class TourStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class DealStage(str, Enum):
    PROSPECT = "PROSPECT"
    LOI_DRAFT = "LOI_DRAFT"
    LOI_COUNTERED = "LOI_COUNTERED"
    LOI_ACCEPTED = "LOI_ACCEPTED"
    LEASE_OUT = "LEASE_OUT"
    EXECUTED = "EXECUTED"
    DEAD = "DEAD"


class ProposalOutcome(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class ProposalSide(str, Enum):
    LISTING = "LISTING"
    TENANT = "TENANT"


class SplitSide(str, Enum):
    LISTING = "LISTING"
    PROCURING = "PROCURING"


# --- Entity TypedDicts (full records carry id/created_at/updated_at/version) ---
class Brokerage(TypedDict):
    id: str
    name: str
    side: str
    default_commission_pct: float
    created_at: str
    updated_at: str
    version: int


class Broker(TypedDict):
    id: str
    brokerage_id: str
    full_name: str
    license_no: str
    role: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    listing_broker_id: str
    name: str
    market: str
    asset_class: str
    total_sf: int
    available_sf: int
    created_at: str
    updated_at: str
    version: int


class Space(TypedDict):
    id: str
    property_id: str
    suite_no: str
    rentable_sf: int
    asking_rent_psf_yr: float
    free_rent_months: int
    ti_allowance_psf: float
    status: str
    held_by_tour_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    space_id: str
    listing_broker_id: str
    term_months: int
    annual_escalation_pct: float
    co_broke_offered_pct: float
    status: str
    open_deal_count: int
    created_at: str
    updated_at: str
    version: int


class Requirement(TypedDict):
    id: str
    tenant_broker_id: str
    tenant_name: str
    market: str
    asset_class: str
    min_sf: int
    max_sf: int
    max_rent_psf_yr: float
    status: str
    match_count: int
    created_at: str
    updated_at: str
    version: int


class Tour(TypedDict):
    id: str
    requirement_id: str
    tenant_broker_id: str
    space_id: str
    window_start: str
    window_end: str
    status: str
    holds_space: bool
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    listing_id: str
    requirement_id: str
    listing_broker_id: str
    procuring_broker_id: str
    is_co_broke: bool
    stage: str
    round_count: int
    accepted_proposal_id: Optional[str]
    total_consideration: float
    total_commission: float
    created_at: str
    updated_at: str
    version: int


class Proposal(TypedDict):
    id: str
    deal_id: str
    from_side: str
    base_rent_psf_yr: float
    term_months: int
    free_rent_months: int
    ti_allowance_psf: float
    annual_escalation_pct: float
    outcome: str
    net_effective_rent_psf_yr: float
    created_at: str
    updated_at: str
    version: int


# --- Leaner records: id + created_at ONLY (no updated_at, no version) ---
class CommissionSplit(TypedDict):
    id: str
    deal_id: str
    broker_id: str
    side: str
    amount: float
    created_at: str


class Comp(TypedDict):
    id: str
    space_id: str
    deal_id: str
    market: str
    effective_rent_psf_yr: float
    term_months: int
    executed_at: str
    created_at: str
