"""Domain types derived from scaffold Tables 1, 2, 7."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums (Table 2 - State Machines)
# ---------------------------------------------------------------------------

class RoomStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class BookingStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SeriesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class WaitlistStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class RoomTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class RecurrenceRule(str, Enum):
    DAILY = "DAILY"
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"


# ---------------------------------------------------------------------------
# Role enum (Table 7 - RBAC)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    EMPLOYEE = "employee"
    MANAGER = "manager"
    FACILITY_ADMIN = "facility_admin"


# ---------------------------------------------------------------------------
# Entity TypedDicts (Table 1)
# ---------------------------------------------------------------------------

class Room(TypedDict, total=False):
    id: str
    name: str
    capacity: int
    floor: int
    amenities: List[str]
    tier: str
    status: str
    hourly_rate_cents: int
    peak_multiplier: float
    peak_hours_start: str
    peak_hours_end: str
    ops_run_index: int
    version: int
    created_at: str
    updated_at: str


class Booking(TypedDict, total=False):
    id: str
    room_id: str
    organizer_id: str
    title: str
    start_time: str
    end_time: str
    attendee_count: int
    status: str
    series_id: Optional[str]
    cost_cents: Optional[int]
    rejection_reason: Optional[str]
    checked_in_at: Optional[str]
    version: int
    created_at: str
    updated_at: str


class Series(TypedDict, total=False):
    id: str
    room_id: str
    organizer_id: str
    title: str
    recurrence_rule: str
    start_time: str
    duration_minutes: int
    attendee_count: int
    series_start_date: str
    series_end_date: str
    status: str
    total_bookings: int
    version: int
    created_at: str
    updated_at: str


class Waitlist(TypedDict, total=False):
    id: str
    room_id: str
    requester_id: str
    title: str
    start_time: str
    end_time: str
    attendee_count: int
    status: str
    position: int
    version: int
    created_at: str
    updated_at: str


class AuditLog(TypedDict, total=False):
    id: str
    timestamp: str
    actor_id: str
    actor_role: str
    action: str
    resource_type: str
    resource_id: str
    details: dict
