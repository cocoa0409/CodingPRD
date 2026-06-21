"""Domain types: entity TypedDicts, status enums, role enum.

All names and fields follow the PRD (the Workplace Desk Booking & Hoteling API).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    FACILITY_MANAGER = "FacilityManager"
    EMPLOYEE = "Employee"
    RECEPTIONIST = "Receptionist"
    ANALYST = "Analyst"


# ---------------------------------------------------------------------------
# Status / enum value sets
# ---------------------------------------------------------------------------
class SiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class FloorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class SeatStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    RETIRED = "RETIRED"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class BookingPrivilege(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class OccupancyStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW_RELEASED = "NO_SHOW_RELEASED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    NONE = "NONE"
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    VOID = "VOID"


class LineStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class NoShowEventKind(str, Enum):
    NO_SHOW = "NO_SHOW"
    GOOD_CHECKIN = "GOOD_CHECKIN"


class VisitorPassStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ResourceType(str, Enum):
    SEAT = "SEAT"
    ROOM = "ROOM"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Primary resources carry id + created_at + updated_at + version.
# CheckIn and NoShowEvent are immutable audit rows: id + created_at only.
# ---------------------------------------------------------------------------
class Site(TypedDict):
    id: str
    name: str
    timezone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Floor(TypedDict):
    id: str
    site_id: str
    level: int
    workday_start_minute: int
    workday_end_minute: int
    capacity_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Neighborhood(TypedDict):
    id: str
    floor_id: str
    name: str
    team_code: Optional[str]
    capacity_cap_pct: int
    seat_count: int
    effective_cap_seats: int
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict):
    id: str
    neighborhood_id: str
    label: str
    is_standing: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    floor_id: str
    label: str
    seats_capacity: int
    turnover_buffer_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict):
    id: str
    email: str
    full_name: str
    team_code: str
    strike_score: int
    booking_privilege: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    employee_id: str
    resource_type: str
    seat_id: Optional[str]
    room_id: Optional[str]
    booking_date: str
    start_minute: int
    end_minute: int
    occupancy_status: str
    billing_status: str
    provisional_chargeback_cents: int
    final_chargeback_cents: int
    checkin_deadline_minute: int
    occupied_minutes: int
    created_at: str
    updated_at: str
    version: int


# Append-only audit row: id + created_at only (no updated_at, no version).
class CheckIn(TypedDict):
    id: str
    reservation_id: str
    checked_in_at_minute: int
    within_grace: bool
    created_at: str


class AmenityRequest(TypedDict):
    id: str
    reservation_id: str
    amenity_code: str
    unit_price_cents: int
    quantity: int
    line_status: str
    line_total_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only audit row: id + created_at only (no updated_at, no version).
class NoShowEvent(TypedDict):
    id: str
    employee_id: str
    reservation_id: str
    kind: str
    delta: int
    created_at: str


class CapacityPolicy(TypedDict):
    id: str
    floor_id: str
    max_active_reservations_per_employee: int
    grace_minutes: int
    enforce_team_zoning: bool
    created_at: str
    updated_at: str
    version: int


class VisitorPass(TypedDict):
    id: str
    host_employee_id: str
    seat_id: str
    visitor_name: str
    booking_date: str
    start_minute: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int
