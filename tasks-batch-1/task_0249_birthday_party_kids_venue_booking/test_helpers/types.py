"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Kids Venue Booking PRD (Sections 2-3). Status enums mirror the
state machines; entities that carry only id + created_at (GuestParty, SystemClock)
omit updated_at and version per PRD Section 2.4.
"""
from enum import Enum
from typing import TypedDict, List, Optional


# ─── Status enums ─────────────────────────────────────────────────────────────

class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"


class RoomStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RoomKind(str, Enum):
    INDOOR = "INDOOR"
    OUTDOOR = "OUTDOOR"


class PackageStatus(str, Enum):
    LISTED = "LISTED"
    RETIRED = "RETIRED"


class StaffStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    INACTIVE = "INACTIVE"


class BookingStatus(str, Enum):
    QUOTE_DRAFT = "QUOTE_DRAFT"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    WEATHER_HOLD = "WEATHER_HOLD"
    RESCHEDULED = "RESCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PaymentStatusEnum(str, Enum):
    UNPAID = "UNPAID"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class AddOnKind(str, Enum):
    CAKE = "CAKE"
    CHARACTER = "CHARACTER"
    EXTRA_TIME = "EXTRA_TIME"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class RequiresSkill(str, Enum):
    ENTERTAINER = "ENTERTAINER"
    COOK = "COOK"
    NONE = "NONE"


class WaiverStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    VOIDED = "VOIDED"


class StaffRole(str, Enum):
    HOST = "HOST"
    ENTERTAINER = "ENTERTAINER"
    COOK = "COOK"


class StaffAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class PaymentDirection(str, Enum):
    CHARGE = "CHARGE"
    REFUND = "REFUND"


class PaymentPurpose(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    CANCELLATION_REFUND = "CANCELLATION_REFUND"


class PaymentLedgerStatus(str, Enum):
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    VENUE_MANAGER = "VenueManager"
    COORDINATOR = "Coordinator"
    GUARDIAN = "Guardian"
    FINANCE_CLERK = "FinanceClerk"


# ─── Entity TypedDicts ────────────────────────────────────────────────────────
# Entities carrying full common fields: id, created_at, updated_at, version.

class Venue(TypedDict):
    id: str
    name: str
    timezone: str
    weather_dependent: bool
    reschedule_lead_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    venue_id: str
    name: str
    room_kind: str
    max_capacity: int
    buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartyPackage(TypedDict):
    id: str
    venue_id: str
    theme: str
    base_price_cents: int
    included_children: int
    per_extra_child_cents: int
    base_duration_minutes: int
    deposit_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    venue_id: str
    full_name: str
    skills: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    venue_id: str
    room_id: str
    package_id: str
    guardian_user_id: str
    event_start_utc: str
    event_end_utc: str
    effective_duration_minutes: int
    children_count: int
    adults_count: int
    headcount_committed: int
    waivers_required: int
    waivers_signed: int
    quote_total_cents: int
    final_total_cents: Optional[int]
    deposit_due_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    payment_status: str
    weather_eligible: bool
    reschedule_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    booking_id: str
    kind: str
    unit_price_cents: int
    quantity: int
    extra_minutes: int
    requires_skill: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    booking_id: str
    child_name: str
    guardian_signature: str
    status: str
    created_at: str
    updated_at: str
    version: int


class StaffAssignment(TypedDict):
    id: str
    booking_id: str
    staff_member_id: str
    role_on_event: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    booking_id: str
    direction: str
    amount_cents: int
    purpose: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only / singleton entities: id + created_at only (PRD Section 2.4).

class GuestParty(TypedDict):
    id: str
    created_at: str
    booking_id: str
    children_delta: int
    adults_delta: int
    reason: str


class SystemClock(TypedDict):
    id: str
    created_at: str
    current_utc: str
