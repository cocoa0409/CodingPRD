"""Domain types: entity TypedDicts, status enums, role enum (from PRD §2, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    VENUE_MANAGER = "VenueManager"
    CHEF = "Chef"
    GUEST = "Guest"
    CUSTOMER_SERVICE = "CustomerService"


class SeriesCadence(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


class CorkagePolicy(str, Enum):
    ALLOWED = "ALLOWED"
    NOT_ALLOWED = "NOT_ALLOWED"


class ChefStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LEAVE = "ON_LEAVE"


class TableMode(str, Enum):
    COMMUNAL = "COMMUNAL"
    PRIVATE = "PRIVATE"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SeatType(str, Enum):
    STANDARD = "STANDARD"
    ACCESSIBLE = "ACCESSIBLE"
    HEAD_TABLE = "HEAD_TABLE"


class SeatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"


class BookingStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    CONFIRMED = "CONFIRMED"
    ATTENDED = "ATTENDED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    REFUNDED = "REFUNDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    FORFEITED = "FORFEITED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    REFUND = "REFUND"


class PaymentDirection(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


# --- Entities carrying the full common-field set (id/created_at/updated_at/version) ---

class SupperClubSeries(TypedDict):
    id: str
    name: str
    cadence: str
    theme: str
    communal_table: bool
    default_seat_capacity: int
    base_seat_price_cents: int
    default_deposit_pct: float
    byob_allowed: bool
    corkage_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict):
    id: str
    name: str
    address: str
    max_capacity: int
    corkage_policy: str
    created_at: str
    updated_at: str
    version: int


class Chef(TypedDict):
    id: str
    name: str
    specialty: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    name: str
    email: str
    phone: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Event(TypedDict):
    id: str
    series_id: str
    venue_id: str
    chef_id: str
    title: str
    event_start: str
    event_end: str
    booking_deadline: str
    table_mode: str
    seat_capacity: int
    seat_price_cents: int
    deposit_pct: float
    byob_allowed: bool
    corkage_fee_cents: int
    status: str
    confirmed_seat_count: int
    available_seat_count: int
    gross_deposit_held_cents: int
    projected_revenue_cents: int
    realized_revenue_cents: int
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    event_id: str
    seat_label: str
    seat_type: str
    status: str
    price_override_cents: Optional[int]
    current_booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MenuCourse(TypedDict):
    id: str
    event_id: str
    course_number: int
    name: str
    description: Optional[str]
    paired_wine_name: Optional[str]
    wine_varietal: Optional[str]
    wine_supplement_cents: int
    contains_allergens: List[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    event_id: str
    guest_id: str
    party_size: int
    seat_ids: List[str]
    table_preference: Optional[str]
    dietary_restrictions: List[str]
    allergy_notes: Optional[str]
    byob_bottles: int
    booking_status: str
    payment_status: str
    deposit_due_cents: int
    deposit_paid_cents: int
    total_price_cents: int
    corkage_due_cents: int
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    event_id: str
    guest_id: str
    booking_id: Optional[str]
    party_size: int
    position: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only ledger entry: carries ONLY id + created_at (no updated_at/version) ---

class Payment(TypedDict):
    id: str
    booking_id: str
    kind: str
    direction: str
    amount_cents: int
    reason: Optional[str]
    created_at: str
