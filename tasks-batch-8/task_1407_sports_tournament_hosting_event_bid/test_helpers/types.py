"""Domain types: entity TypedDicts, status enums, role enum.

All statuses come from the PRD's lifecycle narratives; all entities carry the
common system-managed properties (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class EventPosture(str, Enum):
    BIDDING = "BIDDING"
    AWARDED = "AWARDED"
    PLANNING = "PLANNING"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    COMPETITION_SETUP = "COMPETITION_SETUP"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    SETTLED = "SETTLED"
    BID_LOST = "BID_LOST"
    CANCELLED = "CANCELLED"


class BidStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"


class RequirementStatus(str, Enum):
    PENDING = "PENDING"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    VERIFIED = "VERIFIED"
    RETURNED = "RETURNED"
    WAIVED = "WAIVED"


class VenueStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONTRACTED = "CONTRACTED"
    RELEASED = "RELEASED"


class FieldStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BLACKED_OUT = "BLACKED_OUT"


class HotelBlockStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    CONTRACTED = "CONTRACTED"
    CUTOFF_PASSED = "CUTOFF_PASSED"
    RECONCILED = "RECONCILED"
    SETTLED = "SETTLED"
    RELEASED = "RELEASED"


class RebateTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class DivisionStatus(str, Enum):
    OPEN = "OPEN"
    SEEDING_LOCKED = "SEEDING_LOCKED"
    BRACKET_PUBLISHED = "BRACKET_PUBLISHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TeamStatus(str, Enum):
    ENTERED = "ENTERED"
    WAITLISTED = "WAITLISTED"
    ROSTER_SUBMITTED = "ROSTER_SUBMITTED"
    ELIGIBLE = "ELIGIBLE"
    CHECKED_IN = "CHECKED_IN"
    ELIMINATED = "ELIMINATED"
    FINISHED = "FINISHED"
    CHAMPION = "CHAMPION"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class MatchStatus(str, Enum):
    PENDING_TEAMS = "PENDING_TEAMS"
    SCHEDULED = "SCHEDULED"
    WEATHER_DELAYED = "WEATHER_DELAYED"
    RESCHEDULE_QUEUE = "RESCHEDULE_QUEUE"
    IN_PROGRESS = "IN_PROGRESS"
    FINAL = "FINAL"
    FORFEITED = "FORFEITED"
    CANCELLED = "CANCELLED"


class OfficialStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VETTED = "VETTED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"
    WORKED = "WORKED"


class VolunteerStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    REJECTED = "REJECTED"
    INACTIVE = "INACTIVE"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SignupStatus(str, Enum):
    SIGNED_UP = "SIGNED_UP"
    CONFIRMED = "CONFIRMED"
    WORKED = "WORKED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AlertStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"
    EXPIRED = "EXPIRED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_AUDIT = "UNDER_AUDIT"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    EXPENSES_CERTIFIED = "EXPENSES_CERTIFIED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class UserRole(str, Enum):
    COMMISSION_ADMIN = "CommissionAdmin"
    SANCTIONING_REVIEWER = "SanctioningReviewer"
    CVB_AUDITOR = "CvbAuditor"
    TEAM_REP = "TeamRep"
    OFFICIAL = "Official"
    VOLUNTEER = "Volunteer"
    HOTEL_MANAGER = "HotelManager"
    VENUE_MANAGER = "VenueManager"
    ANY = "Any"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all carry the common system-managed properties)
# ---------------------------------------------------------------------------

class Event(TypedDict, total=False):
    id: str
    name: str
    sanctioning_body: str
    host_city: str
    starts_on: str
    ends_on: str
    posture: str
    active_bid_id: Optional[str]
    registered_team_count: int
    finalized_match_count: int
    created_at: str
    updated_at: str
    version: int


class Bid(TypedDict, total=False):
    id: str
    event_id: str
    cycle_number: int
    status: str
    notes: Optional[str]
    revision_count: int
    submitted_at: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    review_score: int
    created_at: str
    updated_at: str
    version: int


class BidRequirement(TypedDict, total=False):
    id: str
    bid_id: str
    kind: str
    is_mandatory: bool
    weight_points: int
    notes: Optional[str]
    status: str
    evidence_uri: Optional[str]
    evidence_submitted_by_user_id: Optional[str]
    verified_by_user_id: Optional[str]
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    address: str
    rental_fee_cents: int
    revenue_share_pct: float
    contract_uri: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Field(TypedDict, total=False):
    id: str
    venue_id: str
    name: str
    surface_type: str
    has_lights: bool
    slot_minutes: int
    status: str
    blackout_start: Optional[str]
    blackout_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HotelBlock(TypedDict, total=False):
    id: str
    event_id: str
    hotel_name: str
    contracted_rooms_per_night: int
    room_rate_cents: int
    block_start_date: str
    block_end_date: str
    cutoff_date: str
    attrition_allowance_pct: float
    status: str
    picked_up_room_nights: int
    rebate_tier: str
    estimated_rebate_cents: int
    final_rebate_cents: Optional[int]
    attrition_penalty_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RoomBooking(TypedDict, total=False):
    id: str
    hotel_block_id: str
    booker_type: str
    team_id: Optional[str]
    official_id: Optional[str]
    guest_name: str
    rooms_count: int
    check_in_date: str
    check_out_date: str
    rate_cents: int
    room_nights: int
    total_charge_cents: int
    cancellation_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Division(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    team_cap: int
    min_teams: int
    registration_fee_cents: int
    status: str
    entered_team_count: int
    eligible_team_count: int
    bracket_size: Optional[int]
    total_rounds: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    division_id: str
    name: str
    contact_email: str
    strength_rating: int
    roster_player_count: Optional[int]
    status: str
    seed_number: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Match(TypedDict, total=False):
    id: str
    division_id: str
    round_number: int
    bracket_slot: int
    home_team_id: Optional[str]
    away_team_id: Optional[str]
    winner_advances_to_match_id: Optional[str]
    field_id: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    original_scheduled_start: Optional[str]
    status: str
    home_score: Optional[int]
    away_score: Optional[int]
    winner_team_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Official(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    certification_level: str
    needs_housing: bool
    game_limit_per_day: int
    status: str
    assigned_game_count: int
    created_at: str
    updated_at: str
    version: int


class OfficialAssignment(TypedDict, total=False):
    id: str
    match_id: str
    official_id: str
    slot_role: str
    status: str
    released_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict, total=False):
    id: str
    event_id: str
    name: str
    email: str
    background_check_cleared: bool
    status: str
    hours_worked: float
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    event_id: str
    role_needed: str
    starts_at: str
    ends_at: str
    capacity: int
    status: str
    confirmed_count: int
    created_at: str
    updated_at: str
    version: int


class ShiftSignup(TypedDict, total=False):
    id: str
    shift_id: str
    volunteer_id: str
    status: str
    credited_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


class WeatherAlert(TypedDict, total=False):
    id: str
    event_id: str
    venue_id: Optional[str]
    severity: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpactReport(TypedDict, total=False):
    id: str
    event_id: str
    status: str
    projected_attendance: int
    notes: Optional[str]
    projected_room_nights: int
    projected_direct_spend_cents: int
    actual_attendance: Optional[int]
    actual_room_nights: int
    audited_direct_spend_cents: Optional[int]
    created_by_user_id: str
    audited_by_user_id: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    event_id: str
    status: str
    sponsor_contributions_cents: int
    expense_lines: List[dict]
    registration_revenue_cents: int
    rebate_total_cents: int
    sanction_fee_cents: int
    venue_rental_total_cents: int
    officials_stipend_total_cents: int
    expense_total_cents: int
    gross_revenue_cents: int
    net_to_commission_cents: int
    certified_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
