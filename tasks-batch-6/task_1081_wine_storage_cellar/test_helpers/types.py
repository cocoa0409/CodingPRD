"""Domain types: entity TypedDicts, status enums, role enum for the Wine-Storage Cellar API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CELLAR_MEMBER = "CellarMember"
    CELLAR_MANAGER = "CellarManager"
    APPRAISER = "Appraiser"
    INSURANCE_AGENT = "InsuranceAgent"
    AUCTION_BROKER = "AuctionBroker"


class MemberStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class MembershipTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    RESERVE = "RESERVE"


class LockerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    FROZEN = "FROZEN"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class SizeTier(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class ClimateZone(str, Enum):
    RED = "RED"
    WHITE = "WHITE"
    SPARKLING = "SPARKLING"


class OccupancyStatus(str, Enum):
    VACANT = "VACANT"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class ClimateStatus(str, Enum):
    NOMINAL = "NOMINAL"
    BREACH = "BREACH"


class BottleStatus(str, Enum):
    STORED = "STORED"
    WITHDRAWN = "WITHDRAWN"
    IN_TRANSIT = "IN_TRANSIT"
    CONSIGNED = "CONSIGNED"
    SOLD = "SOLD"
    DELIVERED = "DELIVERED"


class ProvenanceStatus(str, Enum):
    DOCUMENTED = "DOCUMENTED"
    UNVERIFIED = "UNVERIFIED"
    DISPUTED = "DISPUTED"


class DrinkWindowStatus(str, Enum):
    TOO_YOUNG = "TOO_YOUNG"
    IN_WINDOW = "IN_WINDOW"
    PAST_PEAK = "PAST_PEAK"


class AppraisalStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class AppraisalMethod(str, Enum):
    MARKET_COMPARABLE = "MARKET_COMPARABLE"
    REPLACEMENT_COST = "REPLACEMENT_COST"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    BOUND = "BOUND"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class CoverageTier(str, Enum):
    BASIC = "BASIC"
    FULL = "FULL"


class MovementRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RequestType(str, Enum):
    INTAKE = "INTAKE"
    WITHDRAWAL = "WITHDRAWAL"


class DeliveryOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class ConsignmentStatus(str, Enum):
    DRAFT = "DRAFT"
    LISTED = "LISTED"
    OFFERED = "OFFERED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    OFFERED = "OFFERED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class MaintenanceWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EntryType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Member(TypedDict):
    id: str
    full_name: str
    email: str
    membership_tier: str
    status: str
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Locker(TypedDict):
    id: str
    label: str
    size_tier: str
    climate_zone: str
    capacity_bottles: int
    member_id: Optional[str]
    occupied_bottles: int
    reserved_bottles: int
    free_bottles: int
    occupancy_status: str
    climate_status: str
    monthly_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Bottle(TypedDict):
    id: str
    member_id: str
    locker_id: Optional[str]
    wine_name: str
    vintage_year: int
    varietal: str
    format_ml: int
    provenance_status: str
    drink_window_start_year: int
    drink_window_end_year: int
    drink_window_status: str
    appraised_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appraisal(TypedDict):
    id: str
    bottle_id: str
    method: str
    base_value_cents: int
    assessed_value_cents: int
    created_by_user_id: str
    effective_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePolicy(TypedDict):
    id: str
    member_id: str
    coverage_tier: str
    covered_bottle_ids: List[str]
    insured_value_cents: int
    premium_cents: int
    bound_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MovementRequest(TypedDict):
    id: str
    member_id: str
    locker_id: str
    request_type: str
    quantity: int
    bottle_ids: Optional[List[str]]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict):
    id: str
    member_id: str
    bottle_ids: List[str]
    courier_ref: str
    slot_start: str
    slot_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Consignment(TypedDict):
    id: str
    bottle_id: str
    member_id: str
    reserve_price_cents: int
    offer_price_cents: Optional[int]
    counter_price_cents: Optional[int]
    hammer_price_cents: Optional[int]
    commission_pct: Optional[float]
    net_proceeds_cents: Optional[int]
    estimated_proceeds_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    member_id: str
    requested_size_tier: str
    requested_climate_zone: str
    position: int
    offered_locker_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict):
    id: str
    locker_id: str
    window_start: str
    window_end: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only event records (common_fields: false — only id + created_at) ---

class LedgerEntry(TypedDict):
    id: str
    member_id: str
    entry_type: str
    amount_cents: int
    signed_amount_cents: int
    reason: str
    related_entity_type: Optional[str]
    related_entity_id: Optional[str]
    created_at: str


class ClimateReading(TypedDict):
    id: str
    locker_id: str
    temperature_c: float
    humidity_pct: float
    in_band: bool
    created_at: str
