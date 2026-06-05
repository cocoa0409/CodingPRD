"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    LISTING_AGENT = "ListingAgent"
    BUYER_AGENT = "BuyerAgent"
    ANONYMOUS = "Anonymous"


class AgentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    PENDING = "PENDING"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class OfferPosture(str, Enum):
    NONE = "NONE"
    SINGLE = "SINGLE"
    MULTIPLE = "MULTIPLE"


class LockboxAccessMode(str, Enum):
    APPOINTMENT_ONLY = "APPOINTMENT_ONLY"
    OPEN_ACCESS = "OPEN_ACCESS"


class LockboxStatus(str, Enum):
    INSTALLED = "INSTALLED"
    DISABLED = "DISABLED"


class ShowingStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class OfferStatus(str, Enum):
    OPEN = "OPEN"
    SELLER_COUNTERED = "SELLER_COUNTERED"
    BUYER_COUNTERED = "BUYER_COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class CounterParty(str, Enum):
    SELLER = "SELLER"
    BUYER = "BUYER"


class ContingencyKind(str, Enum):
    INSPECTION = "INSPECTION"
    APPRAISAL = "APPRAISAL"
    FINANCING = "FINANCING"


class ContingencyStatus(str, Enum):
    PENDING = "PENDING"
    WAIVED = "WAIVED"
    SATISFIED = "SATISFIED"
    FAILED = "FAILED"


# --- Entities carrying the full quartet (id, created_at, updated_at, version) ---

class Brokerage(TypedDict):
    id: str
    name: str
    default_total_commission_pct: float
    default_coop_split_pct: float
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict):
    id: str
    brokerage_id: str
    full_name: str
    license_no: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    listing_agent_id: str
    address: str
    list_price_cents: int
    total_commission_pct: float
    coop_split_pct: float
    status: str
    offer_posture: str
    accepted_offer_id: Optional[str]
    final_sale_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Lockbox(TypedDict):
    id: str
    listing_id: str
    serial_no: str
    access_mode: str
    turnaround_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShowingAppointment(TypedDict):
    id: str
    lockbox_id: str
    buyer_agent_id: str
    buyer_id: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Offer(TypedDict):
    id: str
    listing_id: str
    buyer_id: str
    buyer_agent_id: str
    initial_price_cents: int
    earnest_money_cents: int
    current_price_cents: int
    current_party: str
    round_count: int
    requested_contingencies: List[str]
    status: str
    effective_price_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Contingency(TypedDict):
    id: str
    offer_id: str
    kind: str
    appraised_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionLedger(TypedDict):
    id: str
    listing_id: str
    sale_price_cents: int
    total_commission_cents: int
    coop_commission_cents: int
    listing_side_commission_cents: int
    created_at: str
    updated_at: str
    version: int


# --- Append-only entities (only id + created_at, NO updated_at, NO version) ---

class Buyer(TypedDict):
    id: str
    buyer_agent_id: str
    full_name: str
    max_budget_cents: int
    prequalified_amount_cents: int
    monthly_income_cents: int
    monthly_debt_cents: int
    created_at: str


class CounterRound(TypedDict):
    id: str
    offer_id: str
    round_index: int
    by_party: str
    counter_price_cents: int
    actor_agent_id: str
    created_at: str
