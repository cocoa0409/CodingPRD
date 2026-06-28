"""Domain types: entity TypedDicts, status enums, role enum for the Paint & Sip
Event Studio API."""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ──────────────────────────────────────────────────────────

class StudioStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ArtistStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class EventType(str, Enum):
    PUBLIC_CLASS = "PUBLIC_CLASS"
    PRIVATE_PARTY = "PRIVATE_PARTY"
    FUNDRAISER = "FUNDRAISER"
    CORPORATE = "CORPORATE"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FULL = "FULL"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class BookingMode(str, Enum):
    PUBLIC = "PUBLIC"
    PRIVATE = "PRIVATE"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class WalkInStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"


class GiftCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"


class PaymentMethod(str, Enum):
    GIFT_CARD = "GIFT_CARD"
    STUDIO_CREDIT = "STUDIO_CREDIT"
    CARD = "CARD"


class PaymentRowStatus(str, Enum):
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class UserRole(str, Enum):
    STUDIO_MANAGER = "StudioManager"
    CUSTOMER = "Customer"
    FRONT_DESK = "FrontDesk"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# All mutable entities carry id + created_at + updated_at + version.
# Attendee is the sole append-only entity (id + created_at only).

class Studio(TypedDict):
    id: str
    name: str
    room_capacity_seats: int
    timezone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict):
    id: str
    full_name: str
    hourly_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    birthdate: str
    credit_balance_cents: int
    credit_redeemed_cents: int
    created_at: str
    updated_at: str
    version: int


class StudioEvent(TypedDict):
    id: str
    studio_id: str
    title: str
    event_type: str
    start_utc: str
    end_utc: str
    seats_capacity: int
    price_cents_per_seat: int
    kit_fee_cents: int
    byob_allowed: bool
    min_age: int
    fundraiser_donation_pct: int
    status: str
    seats_reserved: int
    walk_in_seats: int
    seats_available: int
    pledged_donation_cents: int
    settled_donation_cents: int
    created_at: str
    updated_at: str
    version: int


class ArtistAssignment(TypedDict):
    id: str
    event_id: str
    artist_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CanvasKitBatch(TypedDict):
    id: str
    event_id: str
    sku: str
    prepared_count: int
    consumed_count: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    event_id: str
    customer_id: str
    booking_mode: str
    seats: int
    include_supply_kit: bool
    status: str
    payment_status: str
    base_cents: int
    group_discount_pct: int
    kit_charge_cents: int
    total_cents: int
    amount_paid_cents: int
    credit_granted_cents: int
    cancelled_at_hours_before: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only: Attendee carries only id and created_at (no updated_at, no version).
class Attendee(TypedDict):
    id: str
    reservation_id: str
    full_name: str
    age_years: int
    waiver_signed: bool
    created_at: str


class WalkIn(TypedDict):
    id: str
    event_id: str
    party_name: str
    party_size: int
    include_supply_kit: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class GiftCard(TypedDict):
    id: str
    code: str
    issued_value_cents: int
    balance_cents: int
    redeemed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    reservation_id: str
    method: str
    gift_card_id: Optional[str]
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
