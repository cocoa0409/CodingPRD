"""Domain types for the EV Battery Swap API.

Entity TypedDicts, status enums, and role enum. Mutable entities carry
id + created_at + updated_at + version; append-only / reference-data
entities carry only id + created_at (no updated_at, no version) per
PRD §2.4.
"""
from __future__ import annotations
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    MEMBER = "Member"
    STATION_OPERATOR = "StationOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Status / phase enums (PRD §3)
# ---------------------------------------------------------------------------
class StationStatus(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    OFFLINE = "OFFLINE"


class BatteryStatus(str, Enum):
    IDLE = "IDLE"
    CHARGING = "CHARGING"
    IN_USE = "IN_USE"
    FAULT = "FAULT"
    RETIRED = "RETIRED"
    RECYCLED = "RECYCLED"
    IN_TRANSIT = "IN_TRANSIT"


class BatterySohGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    RETIRED_EV = "RETIRED_EV"


class BatteryCascadeStage(str, Enum):
    NONE = "NONE"
    ENERGY_STORAGE = "ENERGY_STORAGE"
    LOW_SPEED_VEHICLE = "LOW_SPEED_VEHICLE"
    END_OF_LIFE = "END_OF_LIFE"


class ChargingSlotStatus(str, Enum):
    EMPTY = "EMPTY"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class TouZone(str, Enum):
    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFF_PEAK = "OFF_PEAK"


class SubscriptionTier(str, Enum):
    NONE = "NONE"
    BASIC = "BASIC"
    PREMIUM = "PREMIUM"


class ReservationStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SwapPhase(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    INSPECTED = "INSPECTED"
    UNINSTALLED = "UNINSTALLED"
    INSTALLED = "INSTALLED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    FAILED = "FAILED"


class DispatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class AuditEventType(str, Enum):
    BATTERY_STATUS_CHANGE = "BATTERY_STATUS_CHANGE"
    SWAP_PHASE_CHANGE = "SWAP_PHASE_CHANGE"
    DISPATCH_CHANGE = "DISPATCH_CHANGE"
    RECALL_APPLIED = "RECALL_APPLIED"
    RESERVATION_CHANGE = "RESERVATION_CHANGE"


# ---------------------------------------------------------------------------
# Mutable entities (PRD §2.4): id + created_at + updated_at + version
# ---------------------------------------------------------------------------
class Station(TypedDict, total=False):
    id: str
    name: str
    latitude: float
    longitude: float
    total_slots: int
    status: str
    idle_battery_count: int
    charging_battery_count: int
    created_at: str
    updated_at: str
    version: int


class Battery(TypedDict, total=False):
    id: str
    serial_number: str
    battery_model_code: str
    station_id: Optional[str]
    status: str
    soc_pct: float
    soh_pct: float
    soh_grade: str
    cycle_count: int
    cascade_stage: str
    warranty_expires_at: str
    recall_flag: bool
    created_at: str
    updated_at: str
    version: int


class ChargingSlot(TypedDict, total=False):
    id: str
    station_id: str
    slot_number: int
    status: str
    battery_id: Optional[str]
    tou_zone: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    vehicle_model_code: str
    owner_member_id: str
    installed_battery_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    name: str
    phone: str
    subscription_tier: str
    subscription_swaps_remaining: int
    no_show_count_30d: int
    reservation_blocked_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    member_id: str
    vehicle_id: str
    station_id: str
    slot_start_at: str
    slot_end_at: str
    status: str
    held_battery_id: Optional[str]
    queue_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SwapEvent(TypedDict, total=False):
    id: str
    reservation_id: str
    vehicle_id: str
    station_id: str
    outgoing_battery_id: Optional[str]
    incoming_battery_id: Optional[str]
    outgoing_soc_pct: Optional[float]
    incoming_soc_pct: Optional[float]
    phase: str
    provisional_total_cents: int
    final_total_cents: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingRecord(TypedDict, total=False):
    id: str
    swap_event_id: str
    member_id: str
    per_swap_base_cents: int
    soc_diff_cents: int
    tou_pass_through_cents: int
    subscription_deduction_cents: int
    amount_due_cents: int
    payment_status: str
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


class DispatchOrder(TypedDict, total=False):
    id: str
    source_station_id: str
    dest_station_id: str
    battery_id: str
    status: str
    dispatched_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / reference-data entities (PRD §2.4): only id + created_at
# (NO updated_at, NO version)
# ---------------------------------------------------------------------------
class BatteryModel(TypedDict, total=False):
    id: str
    code: str
    rated_capacity_kwh: float
    nominal_voltage: float
    ev_soh_floor_pct: float
    manufacturer: str
    created_at: str


class VehicleModel(TypedDict, total=False):
    id: str
    code: str
    name: str
    pack_voltage_min: float
    pack_voltage_max: float
    created_at: str


class CompatibilityRule(TypedDict, total=False):
    id: str
    vehicle_model_code: str
    battery_model_code: str
    connector_match: bool
    bms_handshake_supported: bool
    created_at: str


class SOHAssessment(TypedDict, total=False):
    id: str
    battery_id: str
    capacity_test_kwh: float
    internal_resistance_mohm: float
    avg_temperature_c: float
    cycle_count_at_assessment: int
    degradation_slope: float
    soh_pct_out: float
    soh_grade_out: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    event_type: str
    entity_type: str
    entity_id: str
    from_value: Optional[str]
    to_value: str
    actor_role: str
    actor_id: str
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "StationStatus",
    "BatteryStatus",
    "BatterySohGrade",
    "BatteryCascadeStage",
    "ChargingSlotStatus",
    "TouZone",
    "SubscriptionTier",
    "ReservationStatus",
    "SwapPhase",
    "PaymentStatus",
    "DispatchStatus",
    "AuditEventType",
    "Station",
    "Battery",
    "ChargingSlot",
    "Vehicle",
    "Member",
    "Reservation",
    "SwapEvent",
    "BillingRecord",
    "DispatchOrder",
    "BatteryModel",
    "VehicleModel",
    "CompatibilityRule",
    "SOHAssessment",
    "AuditLog",
]
