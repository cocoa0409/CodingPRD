"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    DISPATCH_MANAGER = "DispatchManager"
    SORT_ASSOCIATE = "SortAssociate"
    DRIVER = "Driver"
    CUSTOMER_SERVICE_AGENT = "CustomerServiceAgent"


class TransitCenterStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ParcelStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SORTED = "SORTED"
    ROUTED = "ROUTED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class ServiceLevel(str, Enum):
    GROUND = "GROUND"
    EXPRESS = "EXPRESS"
    PRIORITY = "PRIORITY"


class HazmatClass(str, Enum):
    NONE = "NONE"
    CLASS_3 = "CLASS_3"
    CLASS_8 = "CLASS_8"


class DeliveryRouteStatus(str, Enum):
    PLANNING = "PLANNING"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryStopStatus(str, Enum):
    PENDING = "PENDING"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    ATTEMPTED = "ATTEMPTED"
    DELIVERED = "DELIVERED"
    REDELIVERY_SCHEDULED = "REDELIVERY_SCHEDULED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AttemptOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    NO_ONE_HOME = "NO_ONE_HOME"
    REFUSED = "REFUSED"
    ADDRESS_ISSUE = "ADDRESS_ISSUE"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


# --- Entities with common_fields: true (id + created_at + updated_at + version) ---


class TransitCenter(TypedDict):
    id: str
    name: str
    hazmat_certified: bool
    sort_capacity: int
    sorted_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    name: str
    hazmat_certified: bool
    vehicle_capacity_kg: float
    failure_points: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Parcel(TypedDict):
    id: str
    tracking_code: str
    weight_kg: float
    service_level: str
    signature_required: bool
    hazmat_class: str
    driver_release_authorized: bool
    sorted_at_center_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    driver_id: str
    origin_center_id: str
    service_date: str
    max_stops: int
    planned_weight_kg: float
    committed_weight_kg: float
    stop_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryStop(TypedDict):
    id: str
    route_id: str
    parcel_id: str
    sequence: int
    window_start_min: int
    window_end_min: int
    attempt_count: int
    redelivery_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    stop_id: str
    requested_start_min: int
    requested_end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only entity with common_fields: false (id + created_at only) ---


class DeliveryAttempt(TypedDict):
    id: str
    stop_id: str
    outcome: str
    signature_name: Optional[str]
    used_driver_release: bool
    attempt_index: int
    created_at: str
