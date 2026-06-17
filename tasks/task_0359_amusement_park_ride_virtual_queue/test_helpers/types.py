"""Domain types: entity TypedDicts, status enums, role enum.

All ten primary resources are mutable and carry the full common field set
(id, created_at, updated_at, version) per the PRD's Common Resource Properties.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status / phase enums ---

class DayPhase(str, Enum):
    OPEN = "OPEN"
    PEAK = "PEAK"
    FULL = "FULL"


class OperationalStatus(str, Enum):
    OPEN = "OPEN"
    DOWN = "DOWN"
    CLOSED = "CLOSED"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class AdmissionStatus(str, Enum):
    ISSUED = "ISSUED"
    ADMITTED = "ADMITTED"
    EXITED = "EXITED"


class PartyStatus(str, Enum):
    FORMING = "FORMING"
    LOCKED = "LOCKED"
    DISBANDED = "DISBANDED"


class MembershipStatus(str, Enum):
    LINKED = "LINKED"
    REMOVED = "REMOVED"


class QueueType(str, Enum):
    VIRTUAL_QUEUE = "VIRTUAL_QUEUE"
    SINGLE_RIDER = "SINGLE_RIDER"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    BOOKED = "BOOKED"
    REDEEMED = "REDEEMED"
    FORFEITED = "FORFEITED"
    REDISTRIBUTED = "REDISTRIBUTED"


class PlanTier(str, Enum):
    MULTI_PASS = "MULTI_PASS"
    SINGLE_PASS = "SINGLE_PASS"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    REFUNDED = "REFUNDED"


class UserRole(str, Enum):
    PARK_ADMIN = "ParkAdmin"
    RIDE_OPERATOR = "RideOperator"
    GUEST_APP = "GuestApp"


# --- Entity TypedDicts (all common_fields: true) ---

class Park(TypedDict):
    id: str
    name: str
    gate_capacity: int
    admitted_count: int
    peak_threshold_pct: float
    day_phase: str
    operating_date: str
    created_at: str
    updated_at: str
    version: int


class Ride(TypedDict):
    id: str
    park_id: str
    name: str
    hourly_throughput: int
    min_height_cm: int
    wheelchair_transfer_required: bool
    single_rider_enabled: bool
    operational_status: str
    booked_slot_count: int
    posted_wait_minutes: int
    created_at: str
    updated_at: str
    version: int


class ReturnWindow(TypedDict):
    id: str
    ride_id: str
    window_start_utc: str
    window_end_utc: str
    slot_capacity: int
    reserved_count: int
    window_status: str
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    park_id: str
    full_name: str
    height_cm: int
    uses_wheelchair: bool
    party_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Party(TypedDict):
    id: str
    park_id: str
    leader_guest_id: str
    member_count: int
    party_status: str
    created_at: str
    updated_at: str
    version: int


class PartyMembership(TypedDict):
    id: str
    party_id: str
    guest_id: str
    membership_status: str
    created_at: str
    updated_at: str
    version: int


class EntitlementPlan(TypedDict):
    id: str
    park_id: str
    tier: str
    price_cents: int
    max_concurrent_holds: int
    surge_multiplier: float
    created_at: str
    updated_at: str
    version: int


class GuestDayTicket(TypedDict):
    id: str
    park_id: str
    guest_id: str
    ticket_date: str
    admission_status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    ride_id: str
    guest_id: str
    return_window_id: str
    party_id: Optional[str]
    queue_type: str
    reservation_status: str
    redistributed_from_window_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LightningLanePurchase(TypedDict):
    id: str
    park_id: str
    guest_id: str
    ride_id: str
    plan_id: str
    charged_cents: int
    hold_status: str
    created_at: str
    updated_at: str
    version: int
