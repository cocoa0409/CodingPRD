"""TypedDict shapes and enums for every resource in the API.

Common fields follow the PRD: every resource carries ``id`` and ``created_at``,
and almost every resource additionally carries ``updated_at`` and ``version``.
``TechInspection`` is the single documented exception — it is an immutable audit
record with ``id`` and ``created_at`` only.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """The seven roles recognized by the ``X-User-Role`` header."""

    SERIES_PROMOTER = "SeriesPromoter"
    VENUE_MANAGER = "VenueManager"
    COMPETITOR_TEAM = "CompetitorTeam"
    SAFETY_OFFICIAL = "SafetyOfficial"
    TICKETING_MANAGER = "TicketingManager"
    SPONSOR_REP = "SponsorRep"
    FINANCE_CONTROLLER = "FinanceController"


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    CLOSED = "CLOSED"


class FloorType(str, Enum):
    DIRT = "DIRT"
    CONCRETE = "CONCRETE"
    ASPHALT = "ASPHALT"


class BookingState(str, Enum):
    TERMS_PROPOSED = "TERMS_PROPOSED"
    COUNTERED = "COUNTERED"
    CONFIRMED = "CONFIRMED"
    WITHDRAWN = "WITHDRAWN"


class TermsSource(str, Enum):
    PROMOTER = "PROMOTER"
    VENUE = "VENUE"


class SalesState(str, Enum):
    SALES_PENDING = "SALES_PENDING"
    ON_SALE = "ON_SALE"
    SALES_HALTED = "SALES_HALTED"
    SALES_CLOSED = "SALES_CLOSED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SafetyState(str, Enum):
    SAFETY_DRAFT = "SAFETY_DRAFT"
    SAFETY_REVIEW = "SAFETY_REVIEW"
    SAFETY_CERTIFIED = "SAFETY_CERTIFIED"
    SAFETY_SUSPENDED = "SAFETY_SUSPENDED"


class ReadinessPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class VehicleClass(str, Enum):
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"


class LogisticsState(str, Enum):
    ENTERED = "ENTERED"
    STAGED = "STAGED"
    WITHDRAWN = "WITHDRAWN"


class TechStatus(str, Enum):
    TECH_PENDING = "TECH_PENDING"
    TECH_CLEARED = "TECH_CLEARED"
    TECH_CONDITIONAL = "TECH_CONDITIONAL"
    TECH_HELD = "TECH_HELD"


class ReadinessVariant(str, Enum):
    PRE_STAGING = "PRE_STAGING"
    POST_STAGING = "POST_STAGING"


class InspectionResult(str, Enum):
    PASSED = "PASSED"
    CONDITIONAL = "CONDITIONAL"
    FAILED = "FAILED"


class DefectSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class SegmentType(str, Enum):
    COMPETITION = "COMPETITION"
    INTERMISSION = "INTERMISSION"


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class VoidReason(str, Enum):
    SALES_HALTED = "SALES_HALTED"
    SALES_CLOSED = "SALES_CLOSED"
    STOP_CANCELLED = "STOP_CANCELLED"


class SponsorCategory(str, Enum):
    FUEL = "FUEL"
    TIRE = "TIRE"
    BEVERAGE = "BEVERAGE"
    RETAIL = "RETAIL"
    AUTOMOTIVE = "AUTOMOTIVE"


class ActivationState(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVATED = "ACTIVATED"
    FULFILLED = "FULFILLED"


class SafetyPlanState(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    RETURNED = "RETURNED"


class MarketingChannel(str, Enum):
    RADIO = "RADIO"
    DIGITAL = "DIGITAL"
    GRASSROOTS = "GRASSROOTS"


class MarketingState(str, Enum):
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class SettlementState(str, Enum):
    PREPARED = "PREPARED"
    DISPUTED = "DISPUTED"
    APPROVED = "APPROVED"


class SettlementVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


# ---------------------------------------------------------------------------
# Envelope shapes
# ---------------------------------------------------------------------------


class ResponseMeta(TypedDict, total=False):
    api_request_id: str
    api_request_timestamp: str
    limit: int
    offset: int
    total_count: int
    has_more: bool


class ErrorData(TypedDict):
    error_id: str
    message: str


# ---------------------------------------------------------------------------
# Resources
# ---------------------------------------------------------------------------


class Season(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    year: int
    season_start_date: str
    season_end_date: str
    market_rotation_cooldown_days: int
    total_marketing_budget_cents: int
    marketing_allocated_cents: int
    marketing_unallocated_cents: int
    booking_count: int
    settled_stop_count: int
    season_net_cents: int
    status: str


class Venue(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    market_code: str
    city: str
    state_code: str
    seat_capacity: int
    floor_type: str
    catch_fence_max_height_ft: int
    medical_bay_count: int
    load_in_hours_required: int
    staging_bay_count: int
    turnaround_hours: int


class VenueBooking(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    season_id: str
    venue_id: str
    tour_date: str
    rental_base_cents: int
    revenue_share_pct: float
    per_ticket_facility_fee_cents: int
    load_in_start_utc: str
    tear_down_end_utc: str
    state: str
    negotiation_round: int
    terms_source: str
    last_counter_by_user_id: Optional[str]
    confirmed_at: Optional[str]
    withdraw_reason: Optional[str]


class TourStop(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    season_id: str
    venue_booking_id: str
    preceding_stop_id: Optional[str]
    market_code: str
    event_date: str
    doors_open_utc: Optional[str]
    show_start_utc: Optional[str]
    show_window_minutes: int
    pit_party_price_cents: int
    pit_party_capacity: int
    pit_party_sold_count: int
    sales_state: str
    safety_state: str
    readiness_posture: str
    expected_attendance: int
    competition_segment_count: int
    run_order_end_offset_minutes: int
    tickets_sold_count: int
    gross_ticket_revenue_cents: int
    addon_revenue_cents: int
    facility_fee_collected_cents: int
    marketing_spend_committed_cents: int
    sponsorship_committed_cents: int
    held_hospitality_seat_count: int
    haul_distance_miles: int
    cancel_reason: Optional[str]


class Competitor(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    team_name: str
    driver_name: str
    home_market_code: str
    vehicle_class: str
    entry_count: int


class VehicleEntry(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    competitor_id: str
    tour_stop_id: str
    vehicle_number: str
    vehicle_weight_lbs: int
    haul_distance_miles: int
    scheduled_arrival_utc: str
    actual_arrival_utc: Optional[str]
    staging_bay_index: Optional[int]
    logistics_state: str
    tech_status: str
    tech_attempt_count: int
    failed_attempt_count: int
    readiness_score: int
    readiness_variant: str
    branding_slots_committed: int


class TechInspection(TypedDict):
    """Immutable audit record: no ``updated_at`` and no ``version``."""

    id: str
    created_at: str
    vehicle_entry_id: str
    attempt_no: int
    result: str
    defect_severity: str
    notes: Optional[str]
    inspected_by_user_id: str


class ShowSegment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_stop_id: str
    featured_vehicle_entry_id: Optional[str]
    segment_type: str
    title: str
    run_order_position: int
    duration_minutes: int
    start_offset_minutes: int
    end_offset_minutes: int
    reset_gap_minutes: int


class TicketTier(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_stop_id: str
    tier_code: str
    price_cents: int
    allotment: int
    reserved_seat_count: int
    sold_seat_count: int
    held_seat_count: int
    available_seat_count: int
    group_min_qty: int
    group_discount_pct: float
    on_sale_start_utc: str
    on_sale_end_utc: str


class TicketOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_stop_id: str
    ticket_tier_id: str
    purchaser_name: str
    purchaser_email: str
    qty: int
    is_group: bool
    pit_party_addon_qty: int
    status: str
    line_subtotal_cents: int
    group_discount_cents: int
    addon_subtotal_cents: int
    addon_discount_cents: int
    facility_fee_cents: int
    total_cents: int
    paid_at: Optional[str]
    refunded_at: Optional[str]
    void_reason: Optional[str]


class Sponsor(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    company_name: str
    category: str
    contact_email: str
    exclusive_category: bool


class SponsorshipActivation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    sponsor_id: str
    tour_stop_id: str
    hospitality_tier_id: Optional[str]
    branded_vehicle_entry_id: Optional[str]
    fee_cents: int
    vehicle_branding_slots: int
    signage_units: int
    hospitality_seat_count: int
    state: str
    obligations_fulfilled_at: Optional[str]
    recognized_fee_cents: int


class SafetyPlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_stop_id: str
    state: str
    barrier_linear_feet: int
    catch_fence_height_ft: int
    medical_als_staff_count: int
    medical_bls_staff_count: int
    ambulance_count: int
    emergency_access_lanes: int
    required_als_staff_count: int
    required_bls_staff_count: int
    required_ambulance_count: int
    required_catch_fence_height_ft: int
    required_emergency_access_lanes: int
    required_barrier_linear_feet: int
    safety_cost_cents: int
    authored_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    return_count: int
    return_reason: Optional[str]


class MarketingAllocation(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_stop_id: str
    channel: str
    amount_cents: int
    state: str
    released_at: Optional[str]


class EventSettlement(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    tour_stop_id: str
    state: str
    variant: str
    prepared_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    ticket_revenue_cents: int
    addon_revenue_cents: int
    facility_fee_cents: int
    sponsorship_revenue_cents: int
    marketing_spend_cents: int
    safety_cost_cents: int
    purse_cents: int
    rental_due_pre_credit_cents: int
    coop_credit_pct: float
    coop_credit_cents: int
    venue_due_cents: int
    collected_cash_cents: int
    net_to_promoter_cents: int
    payout_venue_cents: int
    payout_safety_cents: int
    payout_marketing_cents: int
    payout_purse_cents: int
    promoter_remainder_cents: int
    shortfall_cents: int
    profitability_margin_pct: float
    dispute_reason: Optional[str]
    dispute_count: int


class MarketReport(TypedDict):
    """Payload of the season market report read."""

    season_id: str
    market_rows: List[Dict[str, Any]]
    total_net_cents: int
    settled_stop_count: int
    unsettled_stop_count: int


class ClockState(TypedDict):
    """Payload returned when the logical clock is set."""

    current_utc: str


#: Fields present on every resource except ``TechInspection``.
MUTABLE_COMMON_FIELDS: List[str] = ["id", "created_at", "updated_at", "version"]

#: Fields present on the immutable inspection audit record.
IMMUTABLE_COMMON_FIELDS: List[str] = ["id", "created_at"]
