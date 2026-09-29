"""Domain types for the Beverage Program & Wine List Management API.

Entity TypedDicts, status enums and the role enum, all derived from the PRD.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BEVERAGE_DIRECTOR = "BeverageDirector"
    VENUE_SOMMELIER = "VenueSommelier"
    DISTRIBUTOR_REP = "DistributorRep"
    CONTROLLER = "Controller"
    COMPLIANCE_OFFICER = "ComplianceOfficer"


class WineCategory(str, Enum):
    SPARKLING = "SPARKLING"
    WHITE = "WHITE"
    ROSE = "ROSE"
    RED = "RED"
    DESSERT = "DESSERT"
    FORTIFIED = "FORTIFIED"


class CostingMethod(str, Enum):
    FIFO = "FIFO"
    WEIGHTED_AVERAGE = "WEIGHTED_AVERAGE"


class ProgramPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class DistributorComplianceState(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    HOLD = "HOLD"


class AllocationTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class OfferFulfillmentState(str, Enum):
    OPEN = "OPEN"
    ALLOCATED = "ALLOCATED"
    CLOSED = "CLOSED"


class OfferComplianceState(str, Enum):
    PENDING_LICENSE_CHECK = "PENDING_LICENSE_CHECK"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class ClaimState(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    PARTIALLY_GRANTED = "PARTIALLY_GRANTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    RECEIVED = "RECEIVED"


class BinZone(str, Enum):
    CELLAR = "CELLAR"
    BACKBAR = "BACKBAR"
    RESERVE = "RESERVE"
    OFFSITE = "OFFSITE"


class BinState(str, Enum):
    ACTIVE = "ACTIVE"
    FULL = "FULL"


class LotState(str, Enum):
    ON_HAND = "ON_HAND"
    DEPLETED = "DEPLETED"
    WRITTEN_OFF = "WRITTEN_OFF"


class DepletionReason(str, Enum):
    SALE_BTG = "SALE_BTG"
    SALE_BOTTLE = "SALE_BOTTLE"
    EVENT = "EVENT"
    SPOILAGE = "SPOILAGE"
    STAFF_EDUCATION = "STAFF_EDUCATION"
    REVERSAL = "REVERSAL"


class ListVersionState(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PUBLISHED = "PUBLISHED"
    REPRINT_PENDING = "REPRINT_PENDING"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


class PriceBand(str, Enum):
    VALUE = "VALUE"
    CORE = "CORE"
    PREMIUM = "PREMIUM"
    RESERVE = "RESERVE"


class AvailabilityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_STOCK = "OUT_OF_STOCK"


class PreservationMethod(str, Enum):
    ARGON = "ARGON"
    VACUUM = "VACUUM"
    COOLER = "COOLER"
    NONE = "NONE"


class SlotState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"
    WRITTEN_OFF = "WRITTEN_OFF"


class WriteOffState(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class WriteOffReasonCode(str, Enum):
    CORKED = "CORKED"
    OXIDIZED = "OXIDIZED"
    BREAKAGE = "BREAKAGE"
    PRESERVATION_EXPIRY = "PRESERVATION_EXPIRY"
    TEMPERATURE = "TEMPERATURE"


class EventState(str, Enum):
    PLANNED = "PLANNED"
    PRICED = "PRICED"
    CONFIRMED = "CONFIRMED"
    SETTLED = "SETTLED"
    SETTLEMENT_VOIDED = "SETTLEMENT_VOIDED"
    CANCELLED = "CANCELLED"


class InvestigationState(str, Enum):
    OPEN = "OPEN"
    ESCALATED = "ESCALATED"
    RESOLVED_EXPLAINED = "RESOLVED_EXPLAINED"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"


# --- Entity TypedDicts -------------------------------------------------------
# Every resource carries id + created_at.  All resources except the depletion
# ledger additionally carry updated_at and version.


class Venue(TypedDict):
    id: str
    name: str
    venue_code: str
    costing_method: str
    cogs_target_pct_by_category: dict
    event_cogs_target_pct: float
    corkage_fee_cents: int
    corkage_waiver_purchase_ratio: int
    byo_bottle_limit_per_party: int
    byo_prohibited_categories: List[str]
    priority_rank: int
    last_variance_pct: float
    last_pour_cost_run_at: Optional[str]
    program_posture: str
    cogs_ledger_cents: int
    revenue_ledger_cents: int
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict):
    id: str
    name: str
    license_number: str
    allocation_tier: str
    on_time_delivery_pct: float
    compliance_state: str
    last_review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Wine(TypedDict):
    id: str
    producer: str
    cuvee: str
    vintage_year: int
    category: str
    bottle_size_ml: int
    reference_cost_cents: int
    case_pack: int
    is_allocated: bool
    predecessor_wine_id: Optional[str]
    successor_count: int
    created_at: str
    updated_at: str
    version: int


class AllocationOffer(TypedDict):
    id: str
    distributor_id: str
    wine_id: str
    offered_bottles: int
    unit_cost_cents: int
    response_deadline: str
    fulfillment_state: str
    compliance_state: str
    unallocated_bottles: int
    claim_count: int
    allocated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationClaim(TypedDict):
    id: str
    offer_id: str
    venue_id: str
    requested_bottles: int
    granted_bottles: int
    raw_share: float
    remainder_awarded: bool
    state: str
    created_at: str
    updated_at: str
    version: int


class CellarBin(TypedDict):
    id: str
    venue_id: str
    bin_code: str
    zone: str
    capacity_bottles: int
    temperature_controlled: bool
    bottles_stored: int
    utilization_pct: float
    bin_state: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    venue_id: str
    wine_id: str
    bin_id: str
    source_claim_id: Optional[str]
    bottles_received: int
    bottles_on_hand: int
    bottles_committed: int
    unit_cost_cents: int
    received_at: str
    state: str
    created_at: str
    updated_at: str
    version: int


class DepletionEntry(TypedDict):
    """Append-only ledger event: carries only id and created_at."""
    id: str
    venue_id: str
    wine_id: str
    lot_id: str
    list_entry_id: Optional[str]
    btg_slot_id: Optional[str]
    event_id: Optional[str]
    write_off_id: Optional[str]
    reason: str
    bottles: int
    pours: int
    cogs_cents: int
    revenue_cents: int
    occurred_at: str
    created_at: str


class WineList(TypedDict):
    id: str
    venue_id: str
    name: str
    next_version_no: int
    published_version_no: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ListVersion(TypedDict):
    id: str
    wine_list_id: str
    version_no: int
    supersedes_version_id: Optional[str]
    state: str
    entry_count: int
    stale_entry_count: int
    out_of_stock_entry_count: int
    reprint_required: bool
    revision_round: int
    submitted_by_user_id: Optional[str]
    published_by_user_id: Optional[str]
    published_at: Optional[str]
    printed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ListEntry(TypedDict):
    id: str
    list_version_id: str
    wine_id: str
    bottle_price_cents: int
    price_band: str
    by_the_glass: bool
    pour_size_ml: Optional[int]
    glass_price_cents: Optional[int]
    effective_pours: Optional[int]
    par_bottles: int
    tasting_note: Optional[str]
    education_verified: bool
    availability_state: str
    vintage_stale: bool
    contest_points: float
    sort_rank: int
    created_at: str
    updated_at: str
    version: int


class BtgSlot(TypedDict):
    id: str
    venue_id: str
    list_entry_id: str
    lot_id: str
    slot_index: int
    preservation_method: str
    opened_at: str
    preservation_expires_at: str
    effective_pours: int
    pours_sold: int
    staff_education_pours: int
    spoiled_pours: int
    state: str
    created_at: str
    updated_at: str
    version: int


class SpoilageWriteOff(TypedDict):
    id: str
    venue_id: str
    lot_id: str
    btg_slot_id: Optional[str]
    bottles: int
    reason_code: str
    narrative: str
    state: str
    submitted_by_user_id: str
    approved_by_user_id: Optional[str]
    cogs_cents: int
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WineDinnerEvent(TypedDict):
    id: str
    venue_id: str
    list_version_id: str
    name: str
    starts_at: str
    ends_at: str
    seat_count: int
    pour_plan: List[dict]
    state: str
    beverage_cost_per_seat_cents: Optional[int]
    provisional_gross_cents: Optional[int]
    tier_discount_pct: Optional[float]
    final_ticket_price_cents: Optional[int]
    projected_pour_cost_pct: Optional[float]
    pinned_version_no: Optional[int]
    pinned_version_stale: bool
    settled_cogs_cents: Optional[int]
    settled_revenue_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class VarianceInvestigation(TypedDict):
    id: str
    venue_id: str
    triggered_variance_pct: float
    period_start: str
    period_end: str
    state: str
    escalation_note: Optional[str]
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
