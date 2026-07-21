"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    GUEST = "Guest"
    OPERATOR = "Operator"
    FACILITATOR = "Facilitator"


class RetreatStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    FULL = "FULL"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class RoomKind(str, Enum):
    LODGING = "LODGING"
    COMMON = "COMMON"


class RoomTier(str, Enum):
    PRIVATE = "PRIVATE"
    STANDARD = "STANDARD"
    SHARED_DORM = "SHARED_DORM"


class FacilitatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class BookingStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class CancelledBy(str, Enum):
    GUEST = "GUEST"
    OPERATOR = "OPERATOR"


class PaymentType(str, Enum):
    DEPOSIT = "DEPOSIT"
    BALANCE = "BALANCE"
    REFUND = "REFUND"


class WaiverStatus(str, Enum):
    PENDING = "PENDING"
    SIGNED = "SIGNED"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class ReviewDecision(str, Enum):
    CLEAR = "CLEAR"
    REJECT = "REJECT"


class ActivitySlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class ShuttleDirection(str, Enum):
    ARRIVAL = "ARRIVAL"
    DEPARTURE = "DEPARTURE"


class TransportSegmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class AddOnCategory(str, Enum):
    SPA = "SPA"
    EXCURSION = "EXCURSION"
    MEAL = "MEAL"
    GEAR = "GEAR"


# --- Entities carrying the full quartet (id, created_at, updated_at, version) ---

class Retreat(TypedDict):
    id: str
    name: str
    theme: str
    location: str
    start_date: str
    end_date: str
    capacity: int
    base_price_cents: int
    status: str
    reserved_count: int
    schedule_ready: bool
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    retreat_id: str
    kind: str
    tier: str
    tier_delta_cents: int
    bed_count: int
    label: str
    reserved_beds: int
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    email: str
    full_name: str
    phone: str
    dietary_notes: str
    health_notes: str
    created_at: str
    updated_at: str
    version: int


class Facilitator(TypedDict):
    id: str
    full_name: str
    email: str
    specialty: str
    status: str
    payout_cents: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    retreat_id: str
    guest_id: str
    room_id: str
    party_size: int
    has_special_diet: bool
    status: str
    subtotal_cents: int
    group_discount_pct: float
    discount_cents: int
    special_diet_surcharge_cents: int
    total_cents: int
    tax_cents: int
    grand_total_cents: int
    deposit_cents: int
    balance_due_cents: int
    amount_paid_cents: int
    refund_cents: int
    cancelled_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    booking_id: str
    health_disclosures: str
    signature_name: Optional[str]
    status: str
    review_decision: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ActivitySlot(TypedDict):
    id: str
    retreat_id: str
    facilitator_id: str
    room_id: str
    title: str
    start_datetime: str
    end_datetime: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shuttle(TypedDict):
    id: str
    retreat_id: str
    direction: str
    depart_datetime: str
    seat_capacity: int
    reserved_seats: int
    created_at: str
    updated_at: str
    version: int


class TransportSegment(TypedDict):
    id: str
    booking_id: str
    shuttle_id: str
    seat_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Ledger-style records carrying only id + created_at ---

class Payment(TypedDict):
    id: str
    booking_id: str
    type: str
    amount_cents: int
    note: str
    created_at: str


class AddOn(TypedDict):
    id: str
    name: str
    category: str
    price_cents: int
    created_at: str


class BookingAddOn(TypedDict):
    id: str
    booking_id: str
    addon_id: str
    price_cents_snapshot: int
    created_at: str
