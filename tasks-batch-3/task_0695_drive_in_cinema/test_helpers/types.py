"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    VENUE_OPERATOR = "VenueOperator"
    GATE_ATTENDANT = "GateAttendant"
    PATRON = "Patron"


# --- Status enums ---
class LotStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ShowtimeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WEATHER_HOLD = "WEATHER_HOLD"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class PricingMode(str, Enum):
    PER_CAR = "PER_CAR"
    PER_PERSON = "PER_PERSON"


class FmChannelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class SeasonPassTier(str, Enum):
    SILVER = "SILVER"
    GOLD = "GOLD"


class SeasonPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class OccupancyStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    SCANNED = "SCANNED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class ConcessionOrderStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class PrivateRentalStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class FilmRating(str, Enum):
    G = "G"
    PG = "PG"
    PG13 = "PG13"
    R = "R"


class WeatherSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    CANCELLATION = "CANCELLATION"


class RefundSourceType(str, Enum):
    RESERVATION = "RESERVATION"
    CONCESSION_ORDER = "CONCESSION_ORDER"


class RefundReason(str, Enum):
    WEATHER = "WEATHER"
    VOLUNTARY_CANCEL = "VOLUNTARY_CANCEL"
    RESERVATION_CASCADE = "RESERVATION_CASCADE"


# --- Entity TypedDicts ---

# Venue carries full common fields.
class Venue(TypedDict):
    id: str
    name: str
    timezone: str
    fm_channel_pool: List[str]
    turnaround_buffer_minutes: int
    no_show_grace_minutes: int
    created_at: str
    updated_at: str
    version: int


# Lot carries full common fields.
class Lot(TypedDict):
    id: str
    venue_id: str
    name: str
    stall_count: int
    person_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Film: common_fields=false -> only id + created_at (no updated_at, no version).
class Film(TypedDict):
    id: str
    title: str
    runtime_minutes: int
    rating: str
    created_at: str


# Showtime carries full common fields.
class Showtime(TypedDict):
    id: str
    venue_id: str
    lot_id: str
    primary_film_id: str
    secondary_film_id: Optional[str]
    is_double_feature: bool
    start_utc: str
    end_utc: str
    pricing_mode: str
    base_price_cents: int
    included_occupants: int
    per_extra_person_cents: int
    double_feature_surcharge_cents: int
    status: str
    reserved_stall_count: int
    reserved_person_count: int
    created_at: str
    updated_at: str
    version: int


# FmChannelAssignment carries full common fields.
class FmChannelAssignment(TypedDict):
    id: str
    showtime_id: str
    venue_id: str
    frequency: str
    status: str
    created_at: str
    updated_at: str
    version: int


# SeasonPass carries full common fields.
class SeasonPass(TypedDict):
    id: str
    patron_id: str
    tier: str
    max_redemptions: int
    redemptions_used: int
    valid_from_utc: str
    valid_to_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Reservation carries full common fields.
class Reservation(TypedDict):
    id: str
    showtime_id: str
    lot_id: str
    patron_id: str
    occupant_count: int
    season_pass_id: Optional[str]
    promo_pct: float
    amount_due_cents: int
    amount_paid_cents: int
    stalls_used: int
    gate_code: str
    occupancy_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


# ConcessionItem carries full common fields.
class ConcessionItem(TypedDict):
    id: str
    venue_id: str
    name: str
    unit_price_cents: int
    tax_rate: float
    available: bool
    created_at: str
    updated_at: str
    version: int


# ConcessionOrder carries full common fields.
class ConcessionOrder(TypedDict):
    id: str
    reservation_id: str
    lines: List[dict]
    subtotal_cents: int
    tax_cents: int
    service_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# PrivateRental carries full common fields.
class PrivateRental(TypedDict):
    id: str
    venue_id: str
    lot_id: str
    organizer_id: str
    start_utc: str
    end_utc: str
    flat_venue_fee_cents: int
    per_hour_cents: int
    quote_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# WeatherEvent: common_fields=false -> only id + created_at.
class WeatherEvent(TypedDict):
    id: str
    showtime_id: str
    severity: str
    features_remaining: int
    created_at: str


# RefundRecord: common_fields=false -> only id + created_at.
class RefundRecord(TypedDict):
    id: str
    source_type: str
    reservation_id: Optional[str]
    concession_order_id: Optional[str]
    reason: str
    amount_cents: int
    created_at: str
