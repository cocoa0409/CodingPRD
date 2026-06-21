"""Domain types: entity TypedDicts, status enums, role enum.

Field lists and enum values follow the Fishing Charter Booking PRD §2.4 and §3.
Permit and CatchReport are write-once records (PRD §2.4): they carry only id +
created_at and have neither updated_at nor version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---- Roles (PRD §2.1) ----
class UserRole(str, Enum):
    DOCK_MASTER = "DockMaster"
    FLEET_MANAGER = "FleetManager"
    CAPTAIN = "Captain"
    CUSTOMER = "Customer"


# ---- Status enums (PRD §3) ----
class MarinaStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class DockSlotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class BoatStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    DRYDOCK = "DRYDOCK"


class CaptainStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


class MateStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUSPENDED = "SUSPENDED"


class CharterStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    WEATHER_HOLD = "WEATHER_HOLD"
    SAILED = "SAILED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class SlotReservationStatus(str, Enum):
    HELD = "HELD"
    OCCUPIED = "OCCUPIED"
    RELEASED = "RELEASED"


class CrewAssignmentStatus(str, Enum):
    TENTATIVE = "TENTATIVE"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"
    SETTLED = "SETTLED"
    NO_SHOW = "NO_SHOW"


class AddOnLineStatus(str, Enum):
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    VOIDED = "VOIDED"


# ---- Categorical input enums ----
class TripType(str, Enum):
    INSHORE = "INSHORE"
    OFFSHORE = "OFFSHORE"
    HALF_DAY = "HALF_DAY"


class LicenseGrade(str, Enum):
    OUPV = "OUPV"
    MASTER_50 = "MASTER_50"
    MASTER_100 = "MASTER_100"


class PermitKind(str, Enum):
    FEDERAL_OFFSHORE = "FEDERAL_OFFSHORE"
    STATE_INSHORE = "STATE_INSHORE"


class LoyaltyTier(str, Enum):
    STANDARD = "STANDARD"
    SILVER = "SILVER"
    GOLD = "GOLD"


class AddOnKind(str, Enum):
    BAIT = "BAIT"
    ROD_RENTAL = "ROD_RENTAL"
    FISH_CLEANING = "FISH_CLEANING"
    COOLER_ICE = "COOLER_ICE"


class CrewRoleSlot(str, Enum):
    CAPTAIN = "CAPTAIN"
    MATE = "MATE"


# ---- Entity TypedDicts ----
# Versioned entities (PRD §2.4): id + created_at + updated_at + version.

class Marina(TypedDict):
    id: str
    name: str
    timezone_offset_minutes: int
    slot_count: int
    turnaround_buffer_minutes: int
    status: str
    open_slot_count: int
    created_at: str
    updated_at: str
    version: int


class DockSlot(TypedDict):
    id: str
    marina_id: str
    slot_label: str
    max_boat_length_ft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Boat(TypedDict):
    id: str
    marina_id: str
    name: str
    length_ft: float
    passenger_capacity: int
    offshore_rated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Captain(TypedDict):
    id: str
    marina_id: str
    full_name: str
    uscg_license_grade: str
    license_expires_on: str
    offshore_permit_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Mate(TypedDict):
    id: str
    marina_id: str
    full_name: str
    certified_offshore: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Charter(TypedDict):
    id: str
    marina_id: str
    boat_id: str
    permit_id: Optional[str]
    trip_type: str
    depart_at: str
    return_at: str
    base_seat_price_cents: int
    seats_total: int
    seats_booked: int
    split_charter: bool
    catch_total: int
    weather_reschedule_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SlotReservation(TypedDict):
    id: str
    dock_slot_id: str
    charter_id: str
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    charter_id: str
    captain_id: Optional[str]
    mate_id: Optional[str]
    role_slot: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    charter_id: str
    customer_id: str
    party_size: int
    deposit_due_cents: int
    deposit_paid_cents: int
    seat_subtotal_cents: int
    gratuity_cents: int
    gratuity_input_mode: str
    gratuity_input_value: int
    refund_cents: int
    weather_waiver: bool
    gold_reschedule_waiver_used: bool
    reschedule_fee_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class AddOnLine(TypedDict):
    id: str
    booking_id: str
    addon_kind: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Write-once records (PRD §2.4): id + created_at ONLY (no updated_at, no version).

class Permit(TypedDict):
    id: str
    permit_kind: str
    permit_number: str
    valid_through: str
    daily_bag_limit: int
    created_at: str


class CatchReport(TypedDict):
    id: str
    charter_id: str
    species: str
    fish_count: int
    released_count: int
    reported_at: str
    created_at: str
