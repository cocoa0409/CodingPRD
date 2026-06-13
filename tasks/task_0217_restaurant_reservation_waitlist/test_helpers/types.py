"""Domain types: entity TypedDicts, status enums, role enum.

All types mirror the PRD's entity model. Entities that carry the full
created_at / updated_at / version triple are the "versioned" entities;
SpecialRequest and Notification are append-only and carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    HOST = "Host"
    MANAGER = "Manager"


# ─── Status enums ─────────────────────────────────────────────────────────
class RestaurantStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DiningAreaKind(str, Enum):
    STANDARD = "STANDARD"
    PRIVATE = "PRIVATE"


class DiningAreaStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BOUGHT_OUT = "BOUGHT_OUT"


class TableStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SEATED = "SEATED"
    DIRTY = "DIRTY"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BLOCKED = "BLOCKED"


class ReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    SEATED = "SEATED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    NOTIFIED = "NOTIFIED"
    CONVERTED = "CONVERTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class DepositHoldStatus(str, Enum):
    HELD = "HELD"
    CAPTURED = "CAPTURED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"


class PrivateDiningEventStatus(str, Enum):
    INQUIRY = "INQUIRY"
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SpecialRequestCategory(str, Enum):
    DIETARY = "DIETARY"
    SEATING = "SEATING"
    OCCASION = "OCCASION"
    ACCESSIBILITY = "ACCESSIBILITY"
    OTHER = "OTHER"


class NotificationSubjectType(str, Enum):
    RESERVATION = "RESERVATION"
    WAITLIST_ENTRY = "WAITLIST_ENTRY"


class NotificationChannel(str, Enum):
    SMS = "SMS"
    EMAIL = "EMAIL"


class NotificationTemplate(str, Enum):
    WAITLIST_TABLE_READY = "WAITLIST_TABLE_READY"
    RESERVATION_CONFIRMED = "RESERVATION_CONFIRMED"
    RESERVATION_REMINDER = "RESERVATION_REMINDER"
    NO_SHOW_FEE_CHARGED = "NO_SHOW_FEE_CHARGED"
    RESERVATION_CANCELLED = "RESERVATION_CANCELLED"


# ─── Versioned entities (id + created_at + updated_at + version) ──────────
class Restaurant(TypedDict):
    id: str
    name: str
    timezone: str
    default_turn_time_minutes: int
    cleanup_buffer_minutes: int
    late_cancel_cutoff_hours: int
    no_show_strike_block_threshold: int
    per_seat_deposit_cents: int
    deposit_required_party_threshold: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DiningArea(TypedDict):
    id: str
    restaurant_id: str
    name: str
    kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Table(TypedDict):
    id: str
    dining_area_id: str
    label: str
    min_party_size: int
    max_party_size: int
    turn_time_minutes: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServicePeriod(TypedDict):
    id: str
    restaurant_id: str
    name: str
    start_local_time: str
    end_local_time: str
    slot_interval_minutes: int
    pacing_max_covers_per_slot: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    phone: str
    email: Optional[str]
    no_show_strikes: int
    lifetime_reservations: int
    lifetime_failures: int
    settled_reliability_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    restaurant_id: str
    customer_id: str
    table_id: Optional[str]
    party_size: int
    reservation_start: str
    turn_window_end: str
    release_at: str
    deposit_required: bool
    cancellation_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    restaurant_id: str
    customer_id: str
    party_size: int
    requested_start: str
    joined_at: str
    notify_expires_at: Optional[str]
    notify_count: int
    converted_reservation_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DepositHold(TypedDict):
    id: str
    reservation_id: str
    amount_cents: int
    captured_cents: int
    card_last4: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PrivateDiningEvent(TypedDict):
    id: str
    restaurant_id: str
    dining_area_id: str
    customer_id: str
    party_size: int
    event_start: str
    event_end: str
    food_minimum_cents: int
    deposit_pct: float
    service_charge_pct: float
    deposit_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entities (id + created_at only; NO updated_at, NO version) ─
class SpecialRequest(TypedDict):
    id: str
    reservation_id: str
    category: str
    note: str
    acknowledged: bool
    created_at: str


class Notification(TypedDict):
    id: str
    subject_type: str
    subject_id: str
    channel: str
    template: str
    to_phone: str
    created_at: str
