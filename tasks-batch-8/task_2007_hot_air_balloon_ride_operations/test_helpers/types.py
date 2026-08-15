"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class PermissionStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class BalloonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GROUNDED = "GROUNDED"


class CurrencyStatus(str, Enum):
    CURRENT = "CURRENT"
    EXPIRED = "EXPIRED"


class FlightKind(str, Enum):
    SHARED = "SHARED"
    CHARTER = "CHARTER"


class SeasonTier(str, Enum):
    PEAK = "PEAK"
    REGULAR = "REGULAR"


class FlightStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    WEATHER_REVIEW = "WEATHER_REVIEW"
    CLEARED_FOR_LAUNCH = "CLEARED_FOR_LAUNCH"
    AIRBORNE = "AIRBORNE"
    LANDED = "LANDED"
    CLOSED = "CLOSED"
    NO_GO = "NO_GO"
    CANCELLED = "CANCELLED"


class WeatherDecision(str, Enum):
    NONE = "NONE"
    GO = "GO"
    NO_GO = "NO_GO"


class FlightCancelReason(str, Enum):
    WEATHER = "WEATHER"
    AIRCRAFT = "AIRCRAFT"
    OPERATOR = "OPERATOR"


class BookingStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    FLOWN = "FLOWN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"


class PhotoPackageTier(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    DELUXE = "DELUXE"


class ReservationCancelReason(str, Enum):
    WEATHER_CANCEL = "WEATHER_CANCEL"
    OPERATOR_CANCEL = "OPERATOR_CANCEL"
    CUSTOMER_CANCEL_EARLY = "CUSTOMER_CANCEL_EARLY"
    CUSTOMER_CANCEL_LATE = "CUSTOMER_CANCEL_LATE"


class BriefingDecision(str, Enum):
    GO = "GO"
    NO_GO = "NO_GO"


class BriefingStatus(str, Enum):
    RECORDED = "RECORDED"
    SUPERSEDED = "SUPERSEDED"


class ChaseStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    AT_LANDING = "AT_LANDING"
    RECOVERED = "RECOVERED"
    DEBRIEFED = "DEBRIEFED"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    DENIED = "DENIED"


class RefundReason(str, Enum):
    WEATHER_CANCEL = "WEATHER_CANCEL"
    OPERATOR_CANCEL = "OPERATOR_CANCEL"
    CUSTOMER_CANCEL_EARLY = "CUSTOMER_CANCEL_EARLY"
    CUSTOMER_CANCEL_LATE = "CUSTOMER_CANCEL_LATE"


class PaidVia(str, Enum):
    ORIGINAL_PAYMENT = "ORIGINAL_PAYMENT"
    WALLET_CREDIT = "WALLET_CREDIT"


class PhotoRecordStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"


class UserRole(str, Enum):
    OPERATIONS_MANAGER = "OperationsManager"
    PILOT = "Pilot"
    CUSTOMER = "Customer"
    CHASE_CREW_LEAD = "ChaseCrewLead"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class LaunchSite(TypedDict, total=False):
    id: str
    name: str
    surface_wind_limit_kts: int
    aloft_wind_limit_kts: int
    per_use_fee_cents: int
    permission_status: str
    permission_granted_at: Optional[str]
    permission_expires_on: str
    created_at: str
    updated_at: str
    version: int


class Balloon(TypedDict, total=False):
    id: str
    registration: str
    basket_capacity_passengers: int
    max_gross_weight_lbs: int
    empty_weight_lbs: int
    status: str
    last_inspection_on: Optional[str]
    inspection_due_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pilot(TypedDict, total=False):
    id: str
    name: str
    certificate_number: str
    medical_expires_on: str
    external_pic_hours_180d: float
    external_takeoffs_landings_90d: int
    internal_pic_hours_180d: float
    internal_takeoffs_landings_90d: int
    pic_hours_180d_total: float
    takeoffs_landings_90d_total: int
    faa_currency_met: bool
    operator_currency_met: bool
    currency_status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    name: str
    email: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict, total=False):
    id: str
    scheduled_date: str
    dawn_window_start: str
    dawn_window_end: str
    launch_site_id: str
    balloon_id: str
    pilot_id: str
    kind: str
    fuel_lbs: int
    status: str
    season_tier: str
    seats_sold: int
    seats_available: int
    payload_used_lbs: int
    weather_decision: str
    weather_decision_at: Optional[str]
    cancel_reason: Optional[str]
    duration_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    flight_id: str
    customer_id: str
    party_size: int
    declared_weight_lbs: int
    photo_package_tier: str
    booking_status: str
    payment_status: str
    quoted_fare_cents: int
    final_fare_cents: Optional[int]
    paid_cents: int
    refunded_cents: int
    goodwill_credit_cents: int
    retained_revenue_cents: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Passenger(TypedDict, total=False):
    """Append-only manifest entry: carries only id + created_at (PRD §2.4)."""
    id: str
    reservation_id: str
    name: str
    weight_lbs: int
    is_minor: bool
    created_at: str


class WeatherBriefing(TypedDict, total=False):
    """Append-only observation log: carries only id + created_at (PRD §2.4)."""
    id: str
    flight_id: str
    observed_at: str
    surface_wind_kts: int
    aloft_wind_kts: int
    visibility_mi: float
    precipitation: bool
    decision: str
    status: str
    created_at: str


class ChaseAssignment(TypedDict, total=False):
    id: str
    flight_id: str
    crew_lead_name: str
    vehicle_id: str
    crew_size: int
    status: str
    landing_lat: Optional[float]
    landing_lon: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict, total=False):
    id: str
    reservation_id: str
    reason: str
    requested_amount_cents: int
    approved_amount_cents: Optional[int]
    status: str
    paid_via: Optional[str]
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PhotoPackageRecord(TypedDict, total=False):
    """Cascade-created record: carries only id + created_at (PRD §2.4)."""
    id: str
    reservation_id: str
    tier: str
    photo_count: int
    status: str
    delivered_at: Optional[str]
    created_at: str
