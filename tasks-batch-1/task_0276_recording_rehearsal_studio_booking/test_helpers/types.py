"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Recording / Rehearsal Studio Booking PRD (§2.4, §2.7, §3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────
class UserRole(str, Enum):
    STUDIO_MANAGER = "StudioManager"
    CLIENT = "Client"
    ENGINEER = "Engineer"
    ANONYMOUS = "Anonymous"


# ─── Status enums ─────────────────────────────────────
class BookingScheduleStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class BookingSettlementStatus(str, Enum):
    AWAITING_DEPOSIT = "AWAITING_DEPOSIT"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    BALANCE_DUE = "BALANCE_DUE"
    SETTLED = "SETTLED"
    REFUNDING = "REFUNDING"
    REFUNDED = "REFUNDED"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"


class EngineerTier(str, Enum):
    ASSISTANT = "ASSISTANT"
    STAFF = "STAFF"
    SENIOR = "SENIOR"


class BookingKind(str, Enum):
    HOURLY = "HOURLY"
    BLOCK = "BLOCK"
    LOCKOUT = "LOCKOUT"


class GearRentalStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class EngineerAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class RefundDestination(str, Enum):
    ORIGINAL = "ORIGINAL"
    WALLET = "WALLET"


class LockoutContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class SessionDeliveryStatus(str, Enum):
    DRAFT = "DRAFT"
    DELIVERED = "DELIVERED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    ACCEPTED = "ACCEPTED"


# ─── Entity TypedDicts ────────────────────────────────
# common_fields: true — carry id + created_at + updated_at + version.

class Studio(TypedDict):
    id: str
    name: str
    timezone: str
    deposit_pct: float
    overtime_multiplier: float
    overtime_grace_minutes: int
    cancellation_tier_hours: int
    late_cancel_fee_pct: float
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    studio_id: str
    name: str
    hourly_rate_cents: int
    block_rate_cents: int
    block_hours: int
    turnaround_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Engineer(TypedDict):
    id: str
    studio_id: str
    full_name: str
    tier: str
    hourly_rate_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class GearItem(TypedDict):
    id: str
    studio_id: str
    name: str
    total_units: int
    daily_rate_cents: int
    requires_engineer: bool
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    studio_id: str
    display_name: str
    email: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    studio_id: str
    room_id: str
    client_id: str
    parent_series_id: Optional[str]
    booking_kind: str
    is_series_anchor: bool
    start_at: str
    end_at: str
    actual_end_at: Optional[str]
    schedule_status: str
    settlement_status: str
    base_charge_cents: int
    deposit_due_cents: int
    overtime_cents: int
    total_charge_cents: int
    amount_paid_cents: int
    hold_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GearRental(TypedDict):
    id: str
    booking_id: str
    gear_item_id: str
    units: int
    rental_days: int
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EngineerAssignment(TypedDict):
    id: str
    booking_id: str
    engineer_id: str
    scheduled_hours: float
    billed_hours: float
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    booking_id: str
    client_id: str
    kind: str
    amount_cents: int
    refund_destination: str
    reversed: bool
    created_at: str
    updated_at: str
    version: int


class LockoutContract(TypedDict):
    id: str
    studio_id: str
    room_id: str
    client_id: str
    weekday_mask: List[int]
    daily_start_local: str
    daily_end_local: str
    window_start_date: str
    window_end_date: str
    status: str
    occurrences_generated: int
    created_at: str
    updated_at: str
    version: int


class SessionDelivery(TypedDict):
    id: str
    booking_id: str
    file_manifest: list
    revision_round: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; carry ONLY id + created_at (no updated_at, no version).

class OvertimeRecord(TypedDict):
    id: str
    booking_id: str
    overage_minutes: int
    room_surcharge_cents: int
    engineer_surcharge_cents: int
    created_at: str


class Clock(TypedDict):
    id: str
    current_utc: str
    created_at: str
