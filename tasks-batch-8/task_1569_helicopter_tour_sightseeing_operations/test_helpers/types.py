"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class BasePosture(str, Enum):
    NORMAL = "NORMAL"
    WEATHER_HOLD = "WEATHER_HOLD"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RouteTier(str, Enum):
    SHORT = "SHORT"
    STANDARD = "STANDARD"
    GRAND = "GRAND"


class NoiseClassRequirement(str, Enum):
    QUIET_ONLY = "QUIET_ONLY"
    ANY = "ANY"


class NoiseZone(str, Enum):
    VILLAGE = "VILLAGE"
    RIM = "RIM"
    AIRPORT = "AIRPORT"


class SeasonStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class NoiseClass(str, Enum):
    QUIET = "QUIET"
    STANDARD = "STANDARD"


class AircraftStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    GROUNDED = "GROUNDED"


class PilotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    FATIGUE_LOCKED = "FATIGUE_LOCKED"


class DutyDayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    BOARDING = "BOARDING"
    MANIFEST_CLOSED = "MANIFEST_CLOSED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED_WEATHER = "CANCELLED_WEATHER"
    CANCELLED_OPS = "CANCELLED_OPS"


class CancelReason(str, Enum):
    WEATHER = "WEATHER"
    ROUTE_SUSPENDED = "ROUTE_SUSPENDED"
    AIRCRAFT_GROUNDED = "AIRCRAFT_GROUNDED"
    OPS_MANUAL = "OPS_MANUAL"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    MANIFESTED = "MANIFESTED"
    FLOWN = "FLOWN"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    NO_SHOW = "NO_SHOW"
    CREDITED = "CREDITED"


class CreditStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"


class ComplaintStatus(str, Enum):
    LOGGED = "LOGGED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"
    CLOSED = "CLOSED"


class MatchStatus(str, Enum):
    MATCHED = "MATCHED"
    UNMATCHED = "UNMATCHED"


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    DISPATCHER = "Dispatcher"
    BOOKING_AGENT = "BookingAgent"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    COMMUNITY_REPORTER = "CommunityReporter"
    PILOT = "Pilot"


class Base(TypedDict, total=False):
    id: str
    name: str
    quiet_hours_start_min_utc: int
    quiet_hours_end_min_utc: int
    weather_ceiling_min_ft: int
    weather_visibility_min_sm: int
    weather_wind_max_kt: int
    weather_validity_min: int
    current_waiver_version: str
    complaint_quota_threshold: int
    complaint_window_days: int
    hold_expire_minutes: int
    posture: str
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    route_code: str
    tier: str
    duration_minutes: int
    base_seat_price_cents: int
    fuel_required_lb: int
    min_altitude_ft: int
    noise_sensitive: bool
    noise_zones: List[str]
    min_aircraft_noise_class: str
    turn_minutes: int
    status: str
    substantiated_complaints_30d: int
    created_at: str
    updated_at: str
    version: int


class Season(TypedDict, total=False):
    id: str
    label: str
    start_date: str
    end_date: str
    multiplier_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict, total=False):
    id: str
    tail_number: str
    seat_capacity: int
    empty_weight_lb: int
    empty_moment_lb_in: int
    max_takeoff_weight_lb: int
    fuel_arm_inches: float
    seat_arms_inches: List[float]
    cg_forward_limit_in: float
    cg_aft_limit_in: float
    noise_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pilot(TypedDict, total=False):
    id: str
    display_name: str
    certificate_no: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DutyDay(TypedDict, total=False):
    id: str
    pilot_id: str
    duty_date: str
    flight_minutes_scheduled: int
    flight_minutes_actual: int
    duty_minutes_projected: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict, total=False):
    id: str
    base_id: str
    route_id: str
    aircraft_id: str
    pilot_id: str
    scheduled_departure_utc: str
    scheduled_arrival_utc: str
    rotation_seq: int
    status: str
    pilot_acknowledged: bool
    created_by_user_id: str
    dispatched_by_user_id: Optional[str]
    actual_departure_utc: Optional[str]
    actual_arrival_utc: Optional[str]
    cancel_reason: Optional[str]
    seats_booked: int
    seats_available: int
    estimated_gross_weight_lb: int
    manifested_passenger_count: Optional[int]
    manifested_fuel_lb: Optional[int]
    actual_gross_weight_lb: Optional[int]
    actual_cg_in: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    flight_id: str
    contact_name: str
    contact_email: str
    status: str
    seat_count: int
    quoted_per_seat_cents: int
    quoted_total_cents: int
    season_id: Optional[str]
    credits_applied_cents: int
    paid_cents: int
    refunded_card_cents: int
    credited_cents: int
    retained_fee_cents: int
    waiver_version_pinned: str
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Passenger(TypedDict, total=False):
    id: str
    booking_id: str
    pax_index: int
    full_name: str
    declared_weight_lb: int
    waiver_signed: bool
    waiver_version_signed: Optional[str]
    briefing_completed: bool
    checked_in: bool
    actual_weight_lb: Optional[int]
    seat_number: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RebookingCredit(TypedDict, total=False):
    id: str
    booking_id: str
    amount_cents: int
    redeemed_cents: int
    remaining_cents: int
    issued_at: str
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# WeatherObservation is immutable: carries ONLY id + created_at
# (no updated_at, no version) — PRD §2.4.
class WeatherObservation(TypedDict, total=False):
    id: str
    base_id: str
    observed_at: str
    ceiling_ft: int
    visibility_sm: int
    wind_kt: int
    adverse: bool
    validity_until: str
    created_at: str


class Complaint(TypedDict, total=False):
    id: str
    base_id: str
    zone: str
    observed_at: str
    description: str
    reporter_ref: str
    status: str
    match_status: str
    matched_flight_id: Optional[str]
    matched_route_id: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
