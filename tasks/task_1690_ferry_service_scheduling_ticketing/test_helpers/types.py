"""Domain types: entity TypedDicts, status enums, role enum.

All enums mirror the PRD's named status/value sets. Per PRD §2.5, every
resource in this API carries the full common field set (id, created_at,
updated_at, version); there are no reduced-field resources.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SCHEDULER_ADMIN = "SchedulerAdmin"
    TERMINAL_AGENT = "TerminalAgent"
    CUSTOMER = "Customer"
    CREW_PLANNER = "CrewPlanner"


class Season(str, Enum):
    PEAK = "PEAK"
    OFF_PEAK = "OFF_PEAK"


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"


class VesselStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CrewClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class FareScheduleStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    EFFECTIVE = "EFFECTIVE"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class SailingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN_FOR_BOOKING = "OPEN_FOR_BOOKING"
    BOOKING_CLOSED = "BOOKING_CLOSED"
    BOARDING = "BOARDING"
    DEPARTED = "DEPARTED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    WEATHER = "WEATHER"
    TIDES = "TIDES"
    MECHANICAL = "MECHANICAL"
    CREW_SHORTAGE = "CREW_SHORTAGE"
    OTHER = "OTHER"


class FareClass(str, Enum):
    STANDARD = "STANDARD"
    RESIDENT = "RESIDENT"
    COMMUTER = "COMMUTER"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    MODIFIED = "MODIFIED"
    CHECKED_IN = "CHECKED_IN"
    BOARDED = "BOARDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"
    REBOOKED = "REBOOKED"


class PriorityClass(str, Enum):
    MEDICAL = "MEDICAL"
    COMMUTER = "COMMUTER"
    STANDARD = "STANDARD"


class StandbyStatus(str, Enum):
    WAITING = "WAITING"
    CALLED = "CALLED"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"
    NO_BOARD = "NO_BOARD"


class CredentialClass(str, Enum):
    DECK = "DECK"
    ENGINE = "ENGINE"
    CAPTAIN = "CAPTAIN"


class CrewMemberStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OFF_DUTY = "OFF_DUTY"


class CrewAssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class Route(TypedDict, total=False):
    id: str
    route_code: str
    origin_terminal: str
    destination_terminal: str
    crossing_minutes: int
    turnaround_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vessel(TypedDict, total=False):
    id: str
    vessel_name: str
    vehicle_deck_linear_feet: int
    passenger_capacity: int
    crew_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FareSchedule(TypedDict, total=False):
    id: str
    route_id: str
    season: str
    effective_from: str
    effective_to: str
    passenger_standard_cents: int
    passenger_resident_cents: int
    passenger_commuter_cents: int
    vehicle_standard_base_cents: int
    vehicle_oversize_base_cents: int
    vehicle_overlength_per_foot_cents: int
    fuel_surcharge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sailing(TypedDict, total=False):
    id: str
    route_id: str
    vessel_id: str
    departure_time: str
    arrival_time: str
    season: str
    status: str
    cancel_reason: Optional[str]
    reserved_vehicle_feet: int
    standby_cleared_feet: int
    booked_passengers: int
    reserved_deck_allotment_feet: int
    manning_ok: bool
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    fare_class: str
    refund_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    sailing_id: str
    customer_id: str
    fare_schedule_id: str
    passenger_count: int
    has_vehicle: bool
    vehicle_length_feet: Optional[int]
    status: str
    quoted_fare_cents: int
    final_fare_cents: Optional[int]
    rebooked_to_booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StandbyQueueEntry(TypedDict, total=False):
    id: str
    sailing_id: str
    customer_id: str
    has_vehicle: bool
    vehicle_length_feet: Optional[int]
    passenger_count: int
    priority_class: str
    queued_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    full_name: str
    credential_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    sailing_id: str
    crew_member_id: str
    shift_start: str
    shift_end: str
    status: str
    created_at: str
    updated_at: str
    version: int
