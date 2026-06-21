"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model and state machines. Full-lifecycle resources
carry id + created_at + updated_at + version; the leaner records (WaitEvent,
CancellationRecord, ClockState) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    DISPATCH_ADMIN = "DispatchAdmin"
    DISPATCHER = "Dispatcher"
    CORPORATE_BOOKER = "CorporateBooker"
    AFFILIATE_PARTNER = "AffiliatePartner"
    CHAUFFEUR = "Chauffeur"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AffiliateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VehicleClassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class ChauffeurStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    ON_DUTY = "ON_DUTY"
    ON_TRIP = "ON_TRIP"
    SUSPENDED = "SUSPENDED"


class TripStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    ON_LOCATION = "ON_LOCATION"
    PASSENGER_ABOARD = "PASSENGER_ABOARD"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"
    WRITTEN_OFF = "WRITTEN_OFF"


class FulfillmentMode(str, Enum):
    IN_HOUSE = "IN_HOUSE"
    FARMED_OUT = "FARMED_OUT"


class TripType(str, Enum):
    POINT_TO_POINT = "POINT_TO_POINT"
    HOURLY = "HOURLY"
    AIRPORT = "AIRPORT"


class FlightStatus(str, Enum):
    ON_TIME = "ON_TIME"
    DELAYED = "DELAYED"
    LANDED = "LANDED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class FarmOutStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RECALLED = "RECALLED"


class WaitKind(str, Enum):
    CHAUFFEUR_ARRIVED = "CHAUFFEUR_ARRIVED"
    PASSENGER_BOARDED = "PASSENGER_BOARDED"


class CancellationTier(str, Enum):
    FREE = "FREE"
    TIER1 = "TIER1"
    TIER2 = "TIER2"
    NO_SHOW = "NO_SHOW"


# ---------------------------------------------------------------------------
# Entity TypedDicts — full-lifecycle (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------
class CorporateAccount(TypedDict):
    id: str
    company_name: str
    billing_email: str
    negotiated_discount_pct: float
    default_gratuity_pct: float
    cancellation_grace_minutes: int
    status: str
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Affiliate(TypedDict):
    id: str
    name: str
    market_code: str
    payout_share_pct: float
    status: str
    open_farmouts: int
    created_at: str
    updated_at: str
    version: int


class VehicleClass(TypedDict):
    id: str
    code: str
    base_fare_cents: int
    per_mile_cents: int
    hourly_rate_cents: int
    included_wait_minutes: int
    wait_per_minute_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    vehicle_class_id: str
    plate: str
    turnaround_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Chauffeur(TypedDict):
    id: str
    full_name: str
    home_market_code: str
    rest_buffer_minutes: int
    status: str
    active_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    corporate_account_id: str
    trip_type: str
    vehicle_class_id: str
    pickup_at: str
    planned_drop_at: str
    estimated_miles: float
    charter_hours: float
    tolls_cents: int
    gratuity_pct_override: Optional[float]
    trip_status: str
    settlement_status: str
    fulfillment_mode: str
    quote_estimate_total_cents: Optional[int]
    final_total_cents: Optional[int]
    chargeable_wait_minutes: int
    cancellation_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class FlightTracking(TypedDict):
    id: str
    reservation_id: str
    flight_number: str
    scheduled_arrival_at: str
    estimated_arrival_at: Optional[str]
    meet_and_greet: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict):
    id: str
    reservation_id: str
    chauffeur_id: str
    vehicle_id: str
    window_start_at: str
    window_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FarmOutOrder(TypedDict):
    id: str
    reservation_id: str
    affiliate_id: str
    offered_payout_cents: int
    status: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Leaner records — id + created_at only (no updated_at, no version)
# ---------------------------------------------------------------------------
class WaitEvent(TypedDict):
    id: str
    reservation_id: str
    kind: str
    occurred_at: str
    created_at: str


class CancellationRecord(TypedDict):
    id: str
    reservation_id: str
    tier: str
    lead_minutes: int
    fee_cents: int
    created_at: str


class ClockState(TypedDict):
    id: str
    current_utc: str
    created_at: str
