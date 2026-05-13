"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror PRD prose exactly. Per PRD §2.4:

- Versioned entities (id + created_at + updated_at + version):
  Region, Bike, Rider, Ride, WorkOrder, TransferOrder.

- Geofence carries id + created_at + revision (NO updated_at, NO version);
  revision increments on every shape or active-flag mutation.

- Append-only entities (id + created_at ONLY; NO updated_at, NO version,
  NO revision): LossRecord, AuditLog.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    RIDER = "Rider"
    OPERATOR = "Operator"
    FIELD_STAFF = "FieldStaff"
    ADMIN = "Admin"


# ---------------------------------------------------------------------------
# Bike enums (PRD §3.2)
# ---------------------------------------------------------------------------
class BikeModel(str, Enum):
    STANDARD = "STANDARD"
    E_BIKE = "E_BIKE"


class BikeShelfState(str, Enum):
    OFF_SHELF = "OFF_SHELF"
    ON_SHELF = "ON_SHELF"
    SCRAPPED = "SCRAPPED"


class BikeStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    IN_USE = "IN_USE"
    FAULT = "FAULT"
    RECALL = "RECALL"


class BikeLockState(str, Enum):
    LOCKED = "LOCKED"
    UNLOCKED = "UNLOCKED"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Region density posture (PRD §2.7)
# ---------------------------------------------------------------------------
class DensityPosture(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"


# ---------------------------------------------------------------------------
# Geofence enums (PRD §3.1)
# ---------------------------------------------------------------------------
class GeofenceKind(str, Enum):
    ALLOWED_PARKING = "ALLOWED_PARKING"
    RESTRICTED = "RESTRICTED"
    FORBIDDEN = "FORBIDDEN"


# ---------------------------------------------------------------------------
# Rider enums (PRD §3.3)
# ---------------------------------------------------------------------------
class RiderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# ---------------------------------------------------------------------------
# Ride enums (PRD §3.4, §3.10)
# ---------------------------------------------------------------------------
class RideStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"
    DISPUTED = "DISPUTED"


class SettlementVariant(str, Enum):
    PER_MINUTE = "PER_MINUTE"
    DAILY_CAP = "DAILY_CAP"


class EndFenceKind(str, Enum):
    ALLOWED_PARKING = "ALLOWED_PARKING"
    RESTRICTED = "RESTRICTED"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# WorkOrder enums (PRD §3.6)
# ---------------------------------------------------------------------------
class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class WorkOrderCause(str, Enum):
    USER_REPORT = "USER_REPORT"
    LONG_STATIONARY = "LONG_STATIONARY"
    LOCK_ABNORMAL = "LOCK_ABNORMAL"
    LOW_BATTERY = "LOW_BATTERY"
    RECALL = "RECALL"


class FaultCategory(str, Enum):
    FLAT_TIRE = "FLAT_TIRE"
    BRAKE = "BRAKE"
    LOCK_FAILURE = "LOCK_FAILURE"
    BATTERY_SWAP = "BATTERY_SWAP"
    CHARGING = "CHARGING"
    OTHER = "OTHER"


# ---------------------------------------------------------------------------
# TransferOrder enums (PRD §3.8)
# ---------------------------------------------------------------------------
class TransferStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TransferKind(str, Enum):
    REPLENISH = "REPLENISH"
    CLEARANCE = "CLEARANCE"


# ---------------------------------------------------------------------------
# LossRecord enums (PRD §3.11)
# ---------------------------------------------------------------------------
class LossCause(str, Enum):
    THEFT = "THEFT"
    DAMAGE = "DAMAGE"
    ABANDONED = "ABANDONED"


class LossResponsibility(str, Enum):
    RIDER = "RIDER"
    OPERATOR = "OPERATOR"
    UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# AuditLog enums (PRD §2.9)
# ---------------------------------------------------------------------------
class AuditEventKind(str, Enum):
    BILLING_ADJUSTMENT = "BILLING_ADJUSTMENT"
    OPS_ACTION = "OPS_ACTION"
    EXTERNAL_SYNC = "EXTERNAL_SYNC"


# ---------------------------------------------------------------------------
# Entity TypedDicts — versioned (PRD §2.4)
# ---------------------------------------------------------------------------
class Region(TypedDict, total=False):
    id: str
    name: str
    deployment_quota: int
    low_density_threshold: int
    high_density_threshold: int
    in_zone_return_reward_cents: int
    out_of_zone_penalty_cents: int
    deployed_count: int
    available_count: int
    density_posture: str
    clock_minutes: int
    created_at: str
    updated_at: str
    version: int


class Bike(TypedDict, total=False):
    id: str
    region_id: Optional[str]
    model: str
    lock_id: str
    shelf_state: str
    status: str
    battery_pct: int
    last_lat: Optional[float]
    last_lng: Optional[float]
    last_motion_minute: Optional[int]
    lock_state: str
    fault_categories: List[str]
    current_ride_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Rider(TypedDict, total=False):
    id: str
    name: str
    wallet_balance_cents: int
    monthly_pass_expires_minute: int
    free_minutes_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ride(TypedDict, total=False):
    id: str
    rider_id: str
    bike_id: str
    region_id: str
    status: str
    start_minute: int
    end_minute: Optional[int]
    end_lat: Optional[float]
    end_lng: Optional[float]
    end_fence_kind: Optional[str]
    applied_free_minutes: int
    pass_covered_minutes: int
    chargeable_minutes: int
    base_fare_cents: int
    penalty_cents: int
    reward_cents: int
    final_fare_cents: int
    settlement_variant: Optional[str]
    payment_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    bike_id: str
    region_id: str
    cause: str
    category: str
    status: str
    assigned_operator_id: Optional[str]
    sla_minutes: int
    opened_minute: int
    resolved_minute: Optional[int]
    sla_breached: bool
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferOrder(TypedDict, total=False):
    id: str
    from_region_id: str
    to_region_id: str
    bike_ids: List[str]
    status: str
    dispatched_minute: Optional[int]
    completed_minute: Optional[int]
    kind: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Geofence: id + created_at + revision (PRD §2.4)
# ---------------------------------------------------------------------------
class Geofence(TypedDict, total=False):
    id: str
    region_id: str
    label: str
    kind: str
    polygon: List[Dict[str, float]]
    active: bool
    revision: int
    created_at: str


# ---------------------------------------------------------------------------
# Append-only entities — id + created_at only (PRD §2.4)
# ---------------------------------------------------------------------------
class LossRecord(TypedDict, total=False):
    id: str
    bike_id: str
    region_id: Optional[str]
    cause: str
    responsibility: str
    responsible_party_id: Optional[str]
    financial_impact_cents: int
    scrapped: bool
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    actor_id: str
    event_kind: str
    action: str
    subject_type: str
    subject_id: str
    before: Dict[str, Any]
    after: Dict[str, Any]
    clock_minute: int
    created_at: str


__all__ = [
    "UserRole",
    "BikeModel", "BikeShelfState", "BikeStatus", "BikeLockState",
    "DensityPosture",
    "GeofenceKind",
    "RiderStatus",
    "RideStatus", "SettlementVariant", "EndFenceKind",
    "WorkOrderStatus", "WorkOrderCause", "FaultCategory",
    "TransferStatus", "TransferKind",
    "LossCause", "LossResponsibility",
    "AuditEventKind",
    "Region", "Bike", "Rider", "Ride", "WorkOrder", "TransferOrder",
    "Geofence", "LossRecord", "AuditLog",
]
