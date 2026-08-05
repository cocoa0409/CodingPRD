"""Domain types: entity TypedDicts, status enums, role enum (Multifamily Package & Parcel Room API)."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status / enum vocabularies ──────────────────────────────────────────────

class UserRole(str, Enum):
    PROPERTY_MANAGER = "PropertyManager"
    CONCIERGE_STAFF = "ConciergeStaff"
    RESIDENT = "Resident"
    CARRIER = "Carrier"
    PMS_INTEGRATION = "PmsIntegration"


class OccupancyPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class LockerStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ResidentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    HOLD = "HOLD"
    MOVED_OUT = "MOVED_OUT"


class PackageStatus(str, Enum):
    LOGGED = "LOGGED"
    AWAITING_PICKUP = "AWAITING_PICKUP"
    HELD = "HELD"
    PICKED_UP = "PICKED_UP"
    RETURN_INITIATED = "RETURN_INITIATED"
    RETURNED = "RETURNED"
    DISPOSED = "DISPOSED"


class RetailReturnStatus(str, Enum):
    DROPPED_OFF = "DROPPED_OFF"
    AWAITING_CARRIER = "AWAITING_CARRIER"
    REJECTED = "REJECTED"
    PICKED_UP = "PICKED_UP"


class StorageChargeStatus(str, Enum):
    OUTSTANDING = "OUTSTANDING"
    COLLECTED = "COLLECTED"
    WAIVED = "WAIVED"


class SizeClass(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    OVERSIZE = "OVERSIZE"


class StorageClass(str, Enum):
    AMBIENT = "AMBIENT"
    REFRIGERATED = "REFRIGERATED"


class StorageType(str, Enum):
    AMBIENT = "AMBIENT"
    COLD = "COLD"
    PERISHABLE = "PERISHABLE"


class StorageMode(str, Enum):
    NONE = "NONE"
    LOCKER = "LOCKER"
    SHELF = "SHELF"


class NotifyChannel(str, Enum):
    EMAIL = "EMAIL"
    SMS = "SMS"
    PUSH = "PUSH"


class NotificationKind(str, Enum):
    INITIAL = "INITIAL"
    REMINDER = "REMINDER"
    MOVE_OUT_HOLD = "MOVE_OUT_HOLD"
    RETURN_NOTICE = "RETURN_NOTICE"
    DISPOSED_NOTICE = "DISPOSED_NOTICE"


class ChargeType(str, Enum):
    HOLDING_FEE = "HOLDING_FEE"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# All entities below carry id + created_at + updated_at + version, EXCEPT
# Notification, which is immutable (id + created_at only).

class Property(TypedDict):
    id: str
    name: str
    timezone: str
    overflow_threshold_pct: float
    aging_days_standard: int
    aging_days_perishable: int
    perishable_hold_hours: int
    holding_fee_grace_days: int
    holding_fee_daily_cents: int
    perishable_fee_multiplier: float
    oversize_surcharge_cents: int
    holding_fee_cap_cents: int
    return_staging_capacity: int
    occupancy_posture: str
    occupied_locker_count: int
    in_service_locker_count: int
    uncollected_fee_cents: int
    return_staging_count: int
    created_at: str
    updated_at: str
    version: int


class LockerBank(TypedDict):
    id: str
    property_id: str
    label: str
    storage_class: str
    nominal_locker_count: int
    available_locker_count: int
    created_at: str
    updated_at: str
    version: int


class Locker(TypedDict):
    id: str
    locker_bank_id: str
    size_class: str
    storage_class: str
    status: str
    current_package_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shelf(TypedDict):
    id: str
    property_id: str
    zone: str
    storage_class: str
    capacity: int
    occupied_count: int
    created_at: str
    updated_at: str
    version: int


class Resident(TypedDict):
    id: str
    property_id: str
    unit_number: str
    full_name: str
    email: str
    phone: Optional[str]
    notify_channel: str
    loyalty_discount_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Carrier(TypedDict):
    id: str
    property_id: str
    name: str
    scac: str
    allows_smart_locker_delivery: bool
    created_at: str
    updated_at: str
    version: int


class Package(TypedDict):
    id: str
    property_id: str
    resident_id: str
    carrier_id: str
    locker_id: Optional[str]
    shelf_id: Optional[str]
    tracking_number: str
    size_class: str
    storage_type: str
    is_oversize: bool
    storage_mode: str
    pickup_code: Optional[str]
    status: str
    intake_at: str
    notified_at: Optional[str]
    cold_chain_deadline_at: Optional[str]
    aging_deadline_at: str
    provisional_fee_cents: int
    final_fee_cents: Optional[int]
    notify_count: int
    return_initiated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailReturn(TypedDict):
    id: str
    property_id: str
    resident_id: str
    carrier_id: str
    tracking_number: str
    status: str
    dropped_off_at: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StorageCharge(TypedDict):
    id: str
    package_id: str
    charge_type: str
    amount_cents: int
    status: str
    basis: str
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Notification is immutable after creation: id + created_at only (no updated_at, no version).
class Notification(TypedDict):
    id: str
    package_id: str
    channel: str
    kind: str
    pickup_code: Optional[str]
    sent_at: str
    created_at: str
