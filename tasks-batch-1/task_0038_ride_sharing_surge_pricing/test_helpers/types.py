"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    RIDER = "Rider"
    DRIVER = "Driver"
    DISPATCHER = "Dispatcher"


class HeatLevel(str, Enum):
    COOL = "COOL"
    WARM = "WARM"
    HOT = "HOT"
    BLAZING = "BLAZING"


class DriverStatus(str, Enum):
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    ON_TRIP = "ON_TRIP"


class TripStatus(str, Enum):
    REQUESTED = "REQUESTED"
    MATCHED = "MATCHED"
    ENROUTE = "ENROUTE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class AirportQueueStatus(str, Enum):
    WAITING = "WAITING"
    DISPATCHED = "DISPATCHED"
    WITHDRAWN = "WITHDRAWN"


class QuestStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EARNED = "EARNED"
    EXPIRED = "EXPIRED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    REJECTED = "REJECTED"


class DisputeReason(str, Enum):
    OVERCHARGED = "OVERCHARGED"
    DRIVER_NO_SHOW = "DRIVER_NO_SHOW"
    ROUTE_ERROR = "ROUTE_ERROR"


# common_fields: true — id, created_at, updated_at, version
class Zone(TypedDict):
    id: str
    name: str
    grid_code: str
    is_airport: bool
    base_fare_cents: int
    open_demand_count: int
    available_supply_count: int
    current_multiplier: float
    heat_level: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    name: str
    home_zone_id: str
    current_zone_id: str
    status: str
    active_trip_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict):
    id: str
    name: str
    wallet_balance_cents: int
    home_zone_id: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable event-log row: only id + created_at
class SurgeSnapshot(TypedDict):
    id: str
    zone_id: str
    observed_demand: int
    observed_supply: int
    is_rush_hour: bool
    effective_from: str
    effective_to: str
    ratio: float
    multiplier: float
    capped: bool
    created_at: str


class Trip(TypedDict):
    id: str
    rider_id: str
    pickup_zone_id: str
    dropoff_zone_id: str
    driver_id: Optional[str]
    status: str
    quoted_multiplier: float
    quoted_base_fare_cents: int
    final_fare_cents: int
    driver_payout_cents: int
    refunded_cents: int
    created_at: str
    updated_at: str
    version: int


class AirportQueueEntry(TypedDict):
    id: str
    zone_id: str
    driver_id: str
    position: int
    joined_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Quest(TypedDict):
    id: str
    driver_id: str
    target_trips: int
    bonus_cents: int
    window_start: str
    window_end: str
    completed_trips: int
    status: str
    paid_out_cents: int
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict):
    id: str
    trip_id: str
    rider_id: str
    reason: str
    requested_refund_cents: int
    status: str
    refund_cents: int
    created_at: str
    updated_at: str
    version: int
