"""Domain types: entity TypedDicts, status enums, role enum.

All field names match the PRD exactly. Append-only event records (TripSegment,
WalletTransaction) carry only id + created_at — they have no updated_at/version.
"""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    RIDER = "Rider"
    TECHNICIAN = "Technician"
    PLATFORM_ADMIN = "PlatformAdmin"
    CITY_REGULATOR = "CityRegulator"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class PlanCode(str, Enum):
    STANDARD = "STANDARD"
    LOW_INCOME = "LOW_INCOME"


class ZoneType(str, Enum):
    RIDE_OK = "RIDE_OK"
    SLOW = "SLOW"
    NO_RIDE = "NO_RIDE"
    NO_PARK = "NO_PARK"


class VehicleType(str, Enum):
    SCOOTER = "SCOOTER"
    EBIKE = "EBIKE"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    IN_USE = "IN_USE"
    LOW_BATTERY = "LOW_BATTERY"
    MAINTENANCE = "MAINTENANCE"
    RETIRED = "RETIRED"


class RiderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TripStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SegmentType(str, Enum):
    RIDE = "RIDE"
    PAUSE = "PAUSE"


class TaskType(str, Enum):
    MOVE = "MOVE"
    SWAP = "SWAP"


class TaskStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FineReason(str, Enum):
    BAD_PARKING_NO_PARK = "BAD_PARKING_NO_PARK"
    BAD_PARKING_OUT_OF_ZONE = "BAD_PARKING_OUT_OF_ZONE"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"
    WAIVED = "WAIVED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class TxnType(str, Enum):
    TOPUP = "TOPUP"
    TRIP_CHARGE = "TRIP_CHARGE"
    TRIP_REFUND = "TRIP_REFUND"
    FINE_CHARGE = "FINE_CHARGE"
    FINE_REFUND = "FINE_REFUND"


class MDSReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true carry id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class Plan(TypedDict):
    id: str
    code: str
    unlock_fee_cents: int
    per_minute_cents: int
    daily_cap_cents: int
    slow_zone_discount_pct: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict):
    id: str
    name: str
    zone_type: str
    priority: int
    max_speed_kph: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    vehicle_type: str
    qr_code: str
    battery_pct: int
    current_zone_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict):
    id: str
    email: str
    full_name: str
    plan_id: str
    wallet_balance_cents: int
    outstanding_fine_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trip(TypedDict):
    id: str
    rider_id: str
    vehicle_id: str
    start_zone_id: str
    end_zone_id: Optional[str]
    status: str
    started_at: str
    ended_at: Optional[str]
    estimated_fare_cents: int
    final_fare_cents: int
    billable_minutes: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    name: str
    depot_zone_id: str
    on_shift: bool
    created_at: str
    updated_at: str
    version: int


class RebalancingTask(TypedDict):
    id: str
    vehicle_id: str
    technician_id: Optional[str]
    task_type: str
    target_zone_id: Optional[str]
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Fine(TypedDict):
    id: str
    rider_id: str
    trip_id: str
    reason: str
    amount_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int


class LowIncomeApplication(TypedDict):
    id: str
    rider_id: str
    household_size: int
    annual_income_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MDSReport(TypedDict):
    id: str
    window_start: str
    window_end: str
    trip_count: int
    total_billable_minutes: int
    avg_available_vehicles: float
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only event records — common_fields: false (id + created_at only)
# ---------------------------------------------------------------------------
class TripSegment(TypedDict):
    id: str
    trip_id: str
    segment_type: str
    zone_id: str
    started_at: str
    ended_at: Optional[str]
    duration_seconds: int
    created_at: str


class WalletTransaction(TypedDict):
    id: str
    rider_id: str
    trip_id: Optional[str]
    fine_id: Optional[str]
    txn_type: str
    amount_cents: int
    created_at: str
