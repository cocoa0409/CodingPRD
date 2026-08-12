"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    TOUR_MANAGER = "TourManager"
    PROMOTER = "Promoter"
    VENUE_REP = "VenueRep"
    SETTLEMENT_ACCOUNTANT = "SettlementAccountant"
    ANY = "Any"


class TourStatus(str, Enum):
    PLANNING = "PLANNING"
    ROUTING = "ROUTING"
    ON_SALE = "ON_SALE"
    IN_PROGRESS = "IN_PROGRESS"
    SETTLEMENT_REVIEW = "SETTLEMENT_REVIEW"
    CLOSED = "CLOSED"


class TourPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ShowStatus(str, Enum):
    HOLD_REQUESTED = "HOLD_REQUESTED"
    HOLD_PLACED = "HOLD_PLACED"
    CONFIRMED = "CONFIRMED"
    ADVANCED = "ADVANCED"
    PERFORMED = "PERFORMED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class ShowPosture(str, Enum):
    OPEN = "OPEN"
    GATED = "GATED"


class RoutingLegStatus(str, Enum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PromoterHoldStatus(str, Enum):
    PENDING = "PENDING"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class PacketSectionStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    NOT_REQUIRED = "NOT_REQUIRED"  # immigration only


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    PAID = "PAID"


class VarianceFlag(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MATERIAL = "MATERIAL"


class BudgetCategory(str, Enum):
    VENUE_RENT = "VENUE_RENT"
    CREW = "CREW"
    TRANSPORT = "TRANSPORT"
    BACKLINE = "BACKLINE"
    MARKETING = "MARKETING"
    HOSPITALITY = "HOSPITALITY"
    INSURANCE = "INSURANCE"
    MISC = "MISC"


class MarketingChannel(str, Enum):
    RADIO = "RADIO"
    SOCIAL = "SOCIAL"
    OOH = "OOH"
    PRINT = "PRINT"
    INFLUENCER = "INFLUENCER"


class HoldKind(str, Enum):
    RADIUS_CONFLICT = "RADIUS_CONFLICT"
    VENUE_DOUBLE_BOOK = "VENUE_DOUBLE_BOOK"
    REST_VIOLATION = "REST_VIOLATION"
    BUDGET_OVERRUN = "BUDGET_OVERRUN"
    ADVANCE_OVERDUE = "ADVANCE_OVERDUE"


class HoldSeverity(str, Enum):
    STANDARD = "STANDARD"
    CRITICAL = "CRITICAL"


class ComplianceHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


# All resources carry the common fields of PRD §2.4: id, created_at,
# updated_at, version.

class Tour(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_name: str
    artist_name: str
    window_start_date: str
    window_end_date: str
    posture: str
    status: str
    projected_gross_cents: int
    projected_cost_cents: int
    settled_gross_cents: int
    settled_cost_cents: int


class Market(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_id: str
    market_code: str
    metro_name: str
    country_code: str
    radius_miles: int
    exclusivity_window_days: int
    territory_rank: int


class Venue(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_id: str
    market_id: str
    venue_name: str
    capacity: int
    base_rent_cents: int
    curfew_local_time: str
    available_dates: List[str]
    booked_dates: List[str]


class RoutingLeg(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_id: str
    from_market_id: str
    to_market_id: str
    travel_date: str
    drive_miles: int
    drive_minutes: int
    crew_rest_required: bool
    leg_index: int
    status: str


class Show(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_id: str
    market_id: str
    venue_id: str
    show_date: str
    on_sale_at: str
    capacity: Optional[int]
    tickets_sold: int
    gross_potential_cents: Optional[int]
    avg_ticket_price_cents: int
    projected_gross_cents: int
    projected_cost_cents: int
    posture: str
    status: str


class PromoterHold(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    promoter_name: str
    hold_expires_at: str
    guarantee_cents: int
    versus_pct: int
    counter_count: int
    status: str


class AdvancePacket(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    tech_rider_status: str
    hospitality_status: str
    immigration_status: str
    daysheet_issued: bool
    packet_revision: int


class BudgetLine(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    category: str
    description: str
    estimated_cents: int
    actual_cents: Optional[int]
    is_committed: bool


class MarketingSpend(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    channel: str
    spend_cents: int
    flight_start_date: str
    flight_end_date: str
    attributed_ticket_sales: int
    cpa_cents: Optional[int]


class Settlement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    show_id: str
    box_office_gross_cents: int
    taxes_cents: int
    facility_fees_cents: int
    promoter_expenses_cents: int
    artist_share_cents: int
    variance_cents: int
    variance_flag: str
    status: str


class ComplianceHold(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_id: str
    hold_kind: str
    severity: str
    related_show_id: Optional[str]
    reason: str
    status: str
