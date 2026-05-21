"""Domain types — entity TypedDicts, status enums, role enum.

Field names mirror the PRD verbatim. Two entities carry only id +
created_at because PRD §2.4 declares them append-only audit-shaped:
AirportQueue (positions are renumbered by delete + re-create) and
HeatMapSnapshot (snapshots are immutable once written).
"""
from __future__ import annotations

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    RIDER = "Rider"
    DRIVER = "Driver"
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPUTE_OPS = "DisputeOps"


# ---------------------------------------------------------------------------
# Status enums — PRD §3.2, §3.3, §3.4, §3.6, §3.7
# ---------------------------------------------------------------------------
class DriverStatus(str, Enum):
    OFFLINE = "OFFLINE"
    AVAILABLE = "AVAILABLE"
    EN_ROUTE_PICKUP = "EN_ROUTE_PICKUP"
    ON_TRIP = "ON_TRIP"
    IN_AIRPORT_QUEUE = "IN_AIRPORT_QUEUE"


class RideStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ASSIGNED = "ASSIGNED"
    ON_TRIP = "ON_TRIP"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    DISPUTED = "DISPUTED"
    REFUNDED = "REFUNDED"


class QuestBonusStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DayOfWeek(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class DisputeReasonCode(str, Enum):
    OVERCHARGE = "OVERCHARGE"
    DRIVER_NO_SHOW = "DRIVER_NO_SHOW"
    ROUTE_DEVIATION = "ROUTE_DEVIATION"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true) — carry id + created_at + updated_at + version.
# ---------------------------------------------------------------------------
class GeoGrid(TypedDict, total=False):
    id: str
    code: str
    name: str
    is_airport: bool
    rush_hour_eligible: bool
    active_driver_count: int
    open_demand_count: int
    current_multiplier: float
    last_surge_recomputed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict, total=False):
    id: str
    name: str
    status: str
    current_grid_code: Optional[str]
    quest_id: Optional[str]
    quest_completed_rides: int
    total_earnings_cents: int
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict, total=False):
    id: str
    name: str
    wallet_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RushHourWindow(TypedDict, total=False):
    id: str
    label: str
    day_of_week: str
    start_minute: int
    end_minute: int
    additive_bonus: float
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class QuestBonus(TypedDict, total=False):
    id: str
    name: str
    target_ride_count: int
    bonus_amount_cents: int
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Ride(TypedDict, total=False):
    id: str
    rider_id: str
    driver_id: Optional[str]
    pickup_grid_code: str
    dropoff_grid_code: str
    distance_km: float
    status: str
    base_fare_cents: int
    pickup_multiplier_snapshot: float
    rush_hour_bonus_snapshot: float
    quoted_fare_cents: int
    final_fare_cents: Optional[int]
    driver_earnings_cents: Optional[int]
    requested_at: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    ride_id: str
    rider_id: str
    reason_code: str
    requested_refund_cents: int
    approved_refund_cents: Optional[int]
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (common_fields: false) — carry ONLY id + created_at.
# PRD §2.4: "an AirportQueue row carries only id and created_at; a
# HeatMapSnapshot row likewise carries only id and created_at."
# ---------------------------------------------------------------------------
class AirportQueue(TypedDict, total=False):
    id: str
    created_at: str
    grid_code: str
    driver_id: str
    position: int
    joined_at: str


class HeatMapSnapshot(TypedDict, total=False):
    id: str
    created_at: str
    grid_code: str
    multiplier: float
    active_driver_count: int
    open_demand_count: int
    snapshot_at: str


__all__ = [
    "AirportQueue",
    "DayOfWeek",
    "Dispute",
    "DisputeReasonCode",
    "DisputeStatus",
    "Driver",
    "DriverStatus",
    "GeoGrid",
    "HeatMapSnapshot",
    "QuestBonus",
    "QuestBonusStatus",
    "Ride",
    "RideStatus",
    "Rider",
    "RushHourWindow",
    "UserRole",
]
