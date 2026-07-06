"""Domain types: entity TypedDicts, status enums, role enum.

All types reflect the Snow Tubing Winter Park API contract.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Role enum -------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    GUEST_PATRON = "GuestPatron"
    GROUP_HOST = "GroupHost"
    PARK_OPERATOR = "ParkOperator"
    SAFETY_MARSHAL = "SafetyMarshal"


# --- Status enums ----------------------------------------------------------

class ParkPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class LaneStatus(str, Enum):
    OPEN = "OPEN"
    GROOMING = "GROOMING"
    CLOSED = "CLOSED"


class LaneClosureReason(str, Enum):
    WEATHER = "WEATHER"
    MAINTENANCE = "MAINTENANCE"
    GROUP_RENTAL = "GROUP_RENTAL"


class TimeBlockStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    SWEPT = "SWEPT"


class TicketLifecycleState(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    REFUNDED = "REFUNDED"


class TicketCheckinState(str, Enum):
    NOT_CHECKED_IN = "NOT_CHECKED_IN"
    GEARED_UP = "GEARED_UP"
    ON_LANE = "ON_LANE"


class WaiverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class SeasonPassTier(str, Enum):
    SILVER = "SILVER"
    GOLD = "GOLD"
    RESIDENT_GOLD = "RESIDENT_GOLD"


class SeasonPassStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class GroupReservationRentalType(str, Enum):
    SHARED_SEATS = "SHARED_SEATS"
    EXCLUSIVE_LANE = "EXCLUSIVE_LANE"


class GroupReservationState(str, Enum):
    DRAFT = "DRAFT"
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class EquipmentType(str, Enum):
    TUBE = "TUBE"
    HELMET = "HELMET"
    BOOTS = "BOOTS"


class TubeSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class EquipmentRentalState(str, Enum):
    DISPATCHED = "DISPATCHED"
    RETURNED = "RETURNED"
    DAMAGED = "DAMAGED"


class ConveyorTurnState(str, Enum):
    BOARDED = "BOARDED"
    CLEARED = "CLEARED"


class AddOnCategory(str, Enum):
    FOOD = "FOOD"
    RENTAL_UPGRADE = "RENTAL_UPGRADE"
    HOT_DRINK = "HOT_DRINK"


class AddOnState(str, Enum):
    ORDERED = "ORDERED"
    FULFILLED = "FULFILLED"
    VOIDED = "VOIDED"


class RefundReason(str, Enum):
    WEATHER_CLOSURE = "WEATHER_CLOSURE"
    PATRON_CANCEL = "PATRON_CANCEL"
    GROUP_CANCEL = "GROUP_CANCEL"


# --- Entity TypedDicts -----------------------------------------------------
# Resources that may be mutated carry id + created_at + updated_at + version.
# Append-only logs (WeatherLog, RefundEntry) carry ONLY id + created_at.

class Park(TypedDict):
    id: str
    name: str
    timezone_offset_minutes: int
    resident_zip_prefixes: List[str]
    min_snow_depth_cm: int
    max_safe_wind_kph: int
    operational_posture: str
    open_lane_count: int
    total_capacity_remaining: int
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict):
    id: str
    park_id: str
    label: str
    rider_capacity_per_block: int
    conveyor_cycle_seconds: int
    status: str
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TimeBlock(TypedDict):
    id: str
    park_id: str
    starts_at: str
    ends_at: str
    status: str
    committed_rider_count: int
    created_at: str
    updated_at: str
    version: int


class SessionTicket(TypedDict):
    id: str
    park_id: str
    time_block_id: str
    holder_patron_id: str
    season_pass_id: Optional[str]
    upgraded_from_ticket_id: Optional[str]
    rider_height_cm: int
    rider_age_years: int
    is_resident: bool
    base_price_cents: int
    lifecycle_state: str
    checkin_state: str
    created_at: str
    updated_at: str
    version: int


class Waiver(TypedDict):
    id: str
    patron_id: str
    park_id: str
    signed_at: str
    guardian_name: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonPass(TypedDict):
    id: str
    park_id: str
    holder_patron_id: str
    tier: str
    valid_from: str
    valid_until: str
    redemptions_today_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GroupReservation(TypedDict):
    id: str
    park_id: str
    host_patron_id: str
    time_block_id: str
    lane_id: Optional[str]
    rental_type: str
    party_size: int
    deposit_cents: int
    state: str
    created_at: str
    updated_at: str
    version: int


class EquipmentRental(TypedDict):
    id: str
    ticket_id: str
    equipment_type: str
    tube_size: Optional[str]
    state: str
    created_at: str
    updated_at: str
    version: int


class ConveyorTurn(TypedDict):
    id: str
    lane_id: str
    time_block_id: str
    ticket_id: str
    boarded_at: str
    cleared_at: str
    state: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    park_id: str
    ticket_id: str
    category: str
    unit_price_cents: int
    quantity: int
    line_total_cents: int
    state: str
    created_at: str
    updated_at: str
    version: int


class Patron(TypedDict):
    id: str
    full_name: str
    zip_code: str
    birthdate: str
    created_at: str
    updated_at: str
    version: int


# Append-only logs — id + created_at ONLY (no updated_at, no version).

class WeatherLog(TypedDict):
    id: str
    park_id: str
    observed_at: str
    snow_depth_cm: int
    wind_kph: int
    derived_posture: str
    created_at: str


class RefundEntry(TypedDict):
    id: str
    ticket_id: Optional[str]
    group_reservation_id: Optional[str]
    amount_cents: int
    reason: str
    created_at: str
