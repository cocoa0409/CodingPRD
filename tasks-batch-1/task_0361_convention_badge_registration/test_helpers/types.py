"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this API carry the common fields id, created_at, updated_at,
and version (PRD §2.4), so every entity TypedDict below includes them.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum dimensions ────────────────────────────────────────────────

class ConventionPosture(str, Enum):
    OPEN = "OPEN"
    SOLD_OUT = "SOLD_OUT"
    CLOSED = "CLOSED"


class TicketTier(str, Enum):
    GENERAL = "GENERAL"
    THREE_DAY = "THREE_DAY"
    VIP = "VIP"
    EXHIBITOR = "EXHIBITOR"


class AttendeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BANNED = "BANNED"


class LoyaltyTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_PAYMENT = "PENDING_PAYMENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class BadgeStatus(str, Enum):
    ISSUED = "ISSUED"
    PICKED_UP = "PICKED_UP"
    PRINTED = "PRINTED"
    VOID = "VOID"


class RfidStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ENCODED = "ENCODED"
    DEACTIVATED = "DEACTIVATED"


class ReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class WaitlistEntryStatus(str, Enum):
    ENTERED = "ENTERED"
    WON = "WON"
    LOST = "LOST"


class BoothZone(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    ENDCAP = "ENDCAP"


class BoothBookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    RELEASED = "RELEASED"


class UserRole(str, Enum):
    CONVENTION_ADMIN = "ConventionAdmin"
    REGISTRATION_AGENT = "RegistrationAgent"
    ATTENDEE = "Attendee"
    EXHIBITOR = "Exhibitor"
    ANONYMOUS = "Anonymous"


# ─── Entity TypedDicts (all common_fields: true) ─────────────────────────────

class Convention(TypedDict):
    id: str
    name: str
    event_start_utc: str
    event_end_utc: str
    total_badge_capacity: int
    badges_issued_count: int
    lottery_open_utc: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class TicketType(TypedDict):
    id: str
    convention_id: str
    tier: str
    base_price_cents: int
    tier_capacity: int
    tier_issued_count: int
    is_day_pass: bool
    created_at: str
    updated_at: str
    version: int


class Attendee(TypedDict):
    id: str
    email: str
    full_name: str
    loyalty_tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    convention_id: str
    purchaser_attendee_id: str
    is_group: bool
    status: str
    ticket_subtotal_cents: int
    processing_fee_cents: int
    total_cents: int
    amount_paid_cents: int
    refund_amount_cents: int
    provisional_refund_cents: int
    created_at: str
    updated_at: str
    version: int


class TicketLineItem(TypedDict):
    id: str
    order_id: str
    ticket_type_id: str
    quantity: int
    line_base_cents: int
    line_discounted_cents: int
    created_at: str
    updated_at: str
    version: int


class Badge(TypedDict):
    id: str
    order_id: str
    ticket_type_id: str
    holder_attendee_id: str
    status: str
    rfid_status: str
    rfid_uid: Optional[str]
    transfer_count: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    convention_id: str
    title: str
    start_utc: str
    end_utc: str
    seat_capacity: int
    seats_taken: int
    requires_vip: bool
    created_at: str
    updated_at: str
    version: int


class SessionReservation(TypedDict):
    id: str
    session_id: str
    badge_id: str
    status: str
    waitlist_score: int
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    convention_id: str
    attendee_id: str
    requested_quantity: int
    group_size: int
    priority_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Exhibitor(TypedDict):
    id: str
    convention_id: str
    company_name: str
    contact_email: str
    estimated_booth_cents: int
    actual_booth_cents: int
    created_at: str
    updated_at: str
    version: int


class Booth(TypedDict):
    id: str
    convention_id: str
    booth_code: str
    zone: str
    setup_buffer_hours: int
    created_at: str
    updated_at: str
    version: int


class BoothBooking(TypedDict):
    id: str
    booth_id: str
    exhibitor_id: str
    occupy_start_utc: str
    occupy_end_utc: str
    requested_days: int
    occupied_days: int
    status: str
    created_at: str
    updated_at: str
    version: int
