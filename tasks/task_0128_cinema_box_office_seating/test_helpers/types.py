"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and state machines described in the PRD. Entities that
carry the full common field set (id, created_at, updated_at, version) are
distinguished from the two leaner entities (Distributor, Seat) that carry only
id and created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --- Status / enum types ---

class AuditoriumStatus(str, Enum):
    ACTIVE = "ACTIVE"


class FilmStatus(str, Enum):
    BOOKING = "BOOKING"
    RUNNING = "RUNNING"
    ENDED = "ENDED"


class ShowtimeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_SALE = "ON_SALE"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class PricingProfile(str, Enum):
    STANDARD = "STANDARD"
    MATINEE = "MATINEE"
    PEAK = "PEAK"


class RentalBasis(str, Enum):
    BOX_OFFICE = "BOX_OFFICE"
    RENTAL = "RENTAL"


class SeatClass(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ACCESSIBLE = "ACCESSIBLE"


class SeatOccupancy(str, Enum):
    FREE = "FREE"
    HELD = "HELD"
    SOLD = "SOLD"


class MemberTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ComboStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class OrderStatus(str, Enum):
    HELD = "HELD"
    PAID = "PAID"
    EXCHANGED = "EXCHANGED"
    REFUNDED = "REFUNDED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class TicketState(str, Enum):
    HELD = "HELD"
    SOLD = "SOLD"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class UserRole(str, Enum):
    CINEMA_MANAGER = "CinemaManager"
    BOX_OFFICE_AGENT = "BoxOfficeAgent"
    MEMBER = "Member"
    DISTRIBUTOR = "Distributor"
    ANONYMOUS = "Anonymous"


# --- Entity TypedDicts ---

# common_fields: true
class Auditorium(TypedDict):
    id: str
    name: str
    seat_count: int
    turnaround_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Film(TypedDict):
    id: str
    title: str
    runtime_minutes: int
    distributor_id: str
    release_date: str
    split_schedule: list
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — only id + created_at
class Distributor(TypedDict):
    id: str
    name: str
    minimum_guarantee_cents: int
    created_at: str


# common_fields: true
class Showtime(TypedDict):
    id: str
    auditorium_id: str
    film_id: str
    starts_at: str
    ends_at: str
    pricing_profile: str
    base_price_cents: int
    status: str
    rental_basis: str
    private_rental_fee_cents: int
    seats_sold: int
    seats_held: int
    gross_receipts_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — only id + created_at
class Seat(TypedDict):
    id: str
    showtime_id: str
    row_label: str
    seat_number: int
    seat_class: str
    occupancy: str
    created_at: str


# common_fields: true
class Member(TypedDict):
    id: str
    email: str
    full_name: str
    loyalty_points: int
    tier: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class ConcessionCombo(TypedDict):
    id: str
    name: str
    price_cents: int
    member_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Order(TypedDict):
    id: str
    showtime_id: str
    member_id: str
    seat_ids: List[str]
    combo_ids: List[str]
    apply_wallet_credit: bool
    status: str
    tickets_subtotal_cents: int
    combos_subtotal_cents: int
    wallet_applied_cents: int
    total_charged_cents: int
    hold_expires_at: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Ticket(TypedDict):
    id: str
    order_id: str
    showtime_id: str
    seat_id: str
    member_id: str
    provisional_price_cents: int
    final_price_cents: Optional[int]
    state: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Payment(TypedDict):
    id: str
    order_id: str
    amount_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Settlement(TypedDict):
    id: str
    showtime_id: str
    film_id: str
    distributor_id: str
    gross_receipts_cents: int
    applied_distributor_pct: float
    distributor_share_cents: int
    house_share_cents: int
    created_at: str
    updated_at: str
    version: int
