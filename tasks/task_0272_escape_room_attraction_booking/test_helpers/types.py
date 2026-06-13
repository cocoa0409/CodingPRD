"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Escape Room & Attraction Booking PRD (Sections 2-3).
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    VENUE_MANAGER = "VenueManager"
    GAME_MASTER = "GameMaster"
    CUSTOMER = "Customer"


# ─── Status enums ─────────────────────────────────────
class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class GameMasterStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OFF_DUTY = "OFF_DUTY"


class TimeSlotStatus(str, Enum):
    OPEN = "OPEN"
    HELD = "HELD"
    BOOKED = "BOOKED"
    BLOCKED = "BLOCKED"
    CLOSED = "CLOSED"


class BookingLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class BookingPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    REVOKED = "REVOKED"


class GiftCardStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    VOID = "VOID"


class GiftCardEntryType(str, Enum):
    SPEND = "SPEND"
    REFUND = "REFUND"
    TOPUP = "TOPUP"


# ─── Entity TypedDicts (common_fields: true carry id+created_at+updated_at+version) ──
class Venue(TypedDict):
    id: str
    name: str
    timezone: str
    open_minute_of_day: int
    close_minute_of_day: int
    no_show_fee_pct: float
    no_show_strike_limit: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    venue_id: str
    name: str
    min_group_size: int
    max_group_size: int
    min_age: int
    waiver_required: bool
    base_price_cents: int
    private_surcharge_cents: int
    game_minutes: int
    reset_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PricingRule(TypedDict):
    id: str
    venue_id: str
    room_id: str
    peak_dow_mask: int
    peak_start_minute_of_day: int
    peak_end_minute_of_day: int
    peak_multiplier_bps: int
    large_group_threshold: int
    large_group_multiplier_bps: int
    created_at: str
    updated_at: str
    version: int


class GameMaster(TypedDict):
    id: str
    venue_id: str
    full_name: str
    status: str
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class TimeSlot(TypedDict):
    id: str
    room_id: str
    venue_id: str
    start_utc: str
    game_end_utc: str
    block_end_utc: str
    assigned_game_master_id: Optional[str]
    booking_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    no_show_strike_count: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    venue_id: str
    room_id: str
    time_slot_id: str
    customer_id: str
    gift_card_id: Optional[str]
    group_size: int
    is_private: bool
    quoted_charge_cents: int
    final_charge_cents: int
    gift_card_applied_cents: int
    no_show_fee_cents: int
    lifecycle_status: str
    payment_status: str
    created_at: str
    updated_at: str
    version: int


class Participant(TypedDict):
    id: str
    booking_id: str
    display_name: str
    age: int
    waiver_status: str
    checked_in: bool
    created_at: str
    updated_at: str
    version: int


class GiftCard(TypedDict):
    id: str
    venue_id: str
    code: str
    initial_balance_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only ledger; carries ONLY id + created_at
class GiftCardEntry(TypedDict):
    id: str
    gift_card_id: str
    related_booking_id: Optional[str]
    entry_type: str
    delta_cents: int
    created_at: str
