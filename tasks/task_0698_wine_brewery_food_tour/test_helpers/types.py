"""Domain types: entity TypedDicts, status enums, role enum.

Every primary resource carries id, created_at, updated_at, and version
(see PRD §2.4). All ten entities are common_fields: true.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ------------------------------------------------------------------
class UserRole(str, Enum):
    OPERATOR = "Operator"
    GUIDE = "Guide"
    PARTNER_VENUE = "PartnerVenue"
    GUEST = "Guest"
    ANONYMOUS = "Anonymous"


# --- Status enums -----------------------------------------------------------
class TourProductStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class TourTheme(str, Enum):
    WINE = "WINE"
    BREWERY = "BREWERY"
    FOOD = "FOOD"
    MIXED = "MIXED"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class PartnerVenueKind(str, Enum):
    WINERY = "WINERY"
    BREWERY = "BREWERY"
    RESTAURANT = "RESTAURANT"


class PartnerVenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PickupPointStatus(str, Enum):
    ACTIVE = "ACTIVE"


class DepartureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONFIRMED = "CONFIRMED"
    DEPARTED = "DEPARTED"
    COMPLETED = "COMPLETED"
    CANCELLED_WEATHER = "CANCELLED_WEATHER"
    CANCELLED_OPS = "CANCELLED_OPS"


class StopStatus(str, Enum):
    PLANNED = "PLANNED"
    VISITED = "VISITED"


class VenueConfirmationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"


class BookingStatus(str, Enum):
    DRAFT = "DRAFT"
    RESERVED = "RESERVED"
    PAID = "PAID"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version) ----------
class TourProduct(TypedDict):
    id: str
    name: str
    theme: str
    base_price_per_person_cents: int
    gratuity_pct: float
    charter_fee_cents: int
    min_guest_age: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    tour_product_id: str
    name: str
    price_per_person_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    label: str
    seat_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnerVenue(TypedDict):
    id: str
    name: str
    kind: str
    commission_pct: float
    tasting_cost_per_guest_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupPoint(TypedDict):
    id: str
    name: str
    address: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Departure(TypedDict):
    id: str
    tour_product_id: str
    vehicle_id: str
    depart_at: str
    return_at: str
    is_private_charter: bool
    seat_capacity: int
    seats_taken: int
    expected_headcount: int
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Stop(TypedDict):
    id: str
    departure_id: str
    partner_venue_id: str
    sequence: int
    dwell_minutes: int
    estimated_commission_cents: int
    settled_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VenueConfirmation(TypedDict):
    id: str
    stop_id: str
    partner_venue_id: str
    requested_headcount: int
    revision_count: int
    decline_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    full_name: str
    birth_date: str
    age_verified: bool
    waiver_signed: bool
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    departure_id: str
    lead_guest_id: str
    pickup_point_id: str
    party_size: int
    add_on_id: Optional[str]
    subtotal_cents: int
    gratuity_cents: int
    total_cents: int
    amount_paid_cents: int
    refund_cents: int
    status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int
