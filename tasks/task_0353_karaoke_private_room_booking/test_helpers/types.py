"""Domain types: entity TypedDicts, status enums, role enum.

All field names mirror the Karaoke Private Room Booking PRD exactly.
Song and Payment are immutable (id + created_at only); every other entity
carries the full id/created_at/updated_at/version quartet.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    VENUE_MANAGER = "VenueManager"
    FRONT_DESK = "FrontDesk"
    CUSTOMER = "Customer"


# ─── Status enums ─────────────────────────────────────
class ReservationStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    NO_SHOW = "NO_SHOW"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class QueueEntryStatus(str, Enum):
    PENDING = "PENDING"
    PLAYED = "PLAYED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class FbOrderStatus(str, Enum):
    PLACED = "PLACED"
    VOID = "VOID"


class ExtensionStatus(str, Enum):
    APPLIED = "APPLIED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    SETTLEMENT = "SETTLEMENT"
    REFUND = "REFUND"
    FORFEIT = "FORFEIT"


class RoomTypeName(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    VIP = "VIP"


class SongLanguage(str, Enum):
    EN = "EN"
    JP = "JP"
    KR = "KR"
    ZH = "ZH"
    ES = "ES"
    OTHER = "OTHER"


# ─── Entity TypedDicts (common_fields: true) ──────────
class Venue(TypedDict):
    id: str
    name: str
    timezone: str
    peak_start_minute: int
    peak_end_minute: int
    peak_multiplier: float
    deposit_pct: float
    cancellation_cutoff_hours: int
    grace_minutes: int
    overage_grace_minutes: int
    created_at: str
    updated_at: str
    version: int


class RoomType(TypedDict):
    id: str
    venue_id: str
    name: str
    capacity: int
    base_hourly_rate_cents: int
    fb_minimum_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    venue_id: str
    room_type_id: str
    label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GroupPackage(TypedDict):
    id: str
    venue_id: str
    name: str
    flat_price_cents: int
    included_hours: float
    included_room_type_id: str
    included_fb_credit_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    no_show_strikes: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    venue_id: str
    room_id: str
    room_type_id: str
    customer_id: str
    group_package_id: Optional[str]
    party_size: int
    slot_start_utc: str
    slot_end_utc: str
    status: str
    checked_in_at: Optional[str]
    actual_end_utc: Optional[str]
    quoted_room_subtotal_cents: int
    deposit_cents: int
    settled_room_subtotal_cents: Optional[int]
    fb_consumed_cents: int
    fb_shortfall_cents: int
    final_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Extension(TypedDict):
    id: str
    reservation_id: str
    new_slot_end_utc: str
    added_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class QueueEntry(TypedDict):
    id: str
    reservation_id: str
    song_id: str
    priority: int
    play_order: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FbOrder(TypedDict):
    id: str
    reservation_id: str
    description: str
    unit_price_cents: int
    quantity: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Entity TypedDicts (common_fields: false — id + created_at only) ──
class Song(TypedDict):
    id: str
    venue_id: str
    title: str
    artist: str
    duration_seconds: int
    language: str
    created_at: str


class Payment(TypedDict):
    id: str
    reservation_id: str
    kind: str
    amount_cents: int
    created_at: str
