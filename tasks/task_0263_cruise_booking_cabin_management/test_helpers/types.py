"""Domain types for the Cruise Booking & Cabin Management API.

Entity TypedDicts, status enums, and the role enum. All entities in this
domain carry the full common-field quartet (id, created_at, updated_at,
version) per the PRD's common-resource-properties section.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    REVENUE_MANAGER = "RevenueManager"
    RESERVATIONS_AGENT = "ReservationsAgent"
    GUEST_USER = "GuestUser"
    PORT_AGENT = "PortAgent"
    SYSTEM = "system"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class SailingStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SAILED = "SAILED"
    CANCELLED = "CANCELLED"


class CabinStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    ASSIGNED = "ASSIGNED"
    BLOCKED = "BLOCKED"


class CabinCategoryCode(str, Enum):
    INTERIOR = "INTERIOR"
    OCEANVIEW = "OCEANVIEW"
    BALCONY = "BALCONY"
    SUITE = "SUITE"


class GroupBlockStatus(str, Enum):
    NEGOTIATING = "NEGOTIATING"
    HELD = "HELD"
    PARTIALLY_MATERIALIZED = "PARTIALLY_MATERIALIZED"
    RELEASED = "RELEASED"


class BookingStatus(str, Enum):
    QUOTE = "QUOTE"
    DEPOSIT_HELD = "DEPOSIT_HELD"
    CONFIRMED = "CONFIRMED"
    EMBARKED = "EMBARKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CancellationMode(str, Enum):
    CASH = "CASH"
    FCC = "FCC"


class AddOnKind(str, Enum):
    DINING = "DINING"
    EXCURSION = "EXCURSION"


class AddOnStatus(str, Enum):
    RESERVED = "RESERVED"
    CANCELLED = "CANCELLED"


class DiningVenueCode(str, Enum):
    MAIN = "MAIN"
    SPECIALTY_A = "SPECIALTY_A"
    SPECIALTY_B = "SPECIALTY_B"


class DiningReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    FINAL = "FINAL"
    REFUND = "REFUND"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CAPTURED = "CAPTURED"
    FAILED = "FAILED"
    REFUNDED = "REFUNDED"


class FolioStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    VOID = "VOID"


class FolioGratuityMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FolioChargeStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


# --------------------------------------------------------------------------
# Entity TypedDicts — every entity carries id/created_at/updated_at/version
# --------------------------------------------------------------------------
class Sailing(TypedDict):
    id: str
    ship_name: str
    itinerary_code: str
    embark_date: str
    disembark_date: str
    nights: int
    status: str
    total_cabins: int
    available_cabins: int
    created_at: str
    updated_at: str
    version: int


class CabinCategory(TypedDict):
    id: str
    sailing_id: str
    code: str
    deck_low: int
    deck_high: int
    base_fare_per_guest_cents: int
    max_occupancy: int
    total_cabins: int
    available_cabins: int
    held_cabins: int
    assigned_cabins: int
    blocked_cabins: int
    created_at: str
    updated_at: str
    version: int


class Cabin(TypedDict):
    id: str
    cabin_category_id: str
    sailing_id: str
    cabin_number: str
    deck: int
    status: str
    group_block_id: Optional[str]
    booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GroupBlock(TypedDict):
    id: str
    sailing_id: str
    group_name: str
    cabin_category_id: str
    block_size: int
    group_discount_pct: float
    release_cutoff_date: str
    status: str
    blocked_count: int
    materialized_count: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    sailing_id: str
    cabin_category_id: str
    group_block_id: Optional[str]
    cabin_id: Optional[str]
    owner_user_id: str
    expected_sailing_version: int
    status: str
    guest_count: int
    fare_total_cents: int
    tax_port_total_cents: int
    booking_total_cents: int
    deposit_due_cents: int
    final_due_cents: int
    amount_paid_cents: int
    fcc_credit_cents: int
    cancel_refund_cents: int
    cancellation_mode: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    booking_id: str
    full_name: str
    age: int
    occupancy_index: int
    base_fare_cents: int
    final_fare_cents: int
    tax_port_cents: int
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    booking_id: str
    guest_id: Optional[str]
    kind: str
    title: str
    price_cents: int
    window_start: Optional[str]
    window_end: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DiningReservation(TypedDict):
    id: str
    booking_id: str
    venue_code: str
    seating_start: str
    party_size: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    booking_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Folio(TypedDict):
    id: str
    booking_id: str
    status: str
    gratuity_mode: str
    charges_total_cents: int
    gratuity_total_cents: int
    balance_due_cents: int
    created_at: str
    updated_at: str
    version: int


class FolioCharge(TypedDict):
    id: str
    folio_id: str
    guest_id: Optional[str]
    description: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
