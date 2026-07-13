"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCH_PLANNER = "DispatchPlanner"
    DOCK_COORDINATOR = "DockCoordinator"
    DELIVERY_LEAD = "DeliveryLead"
    CUSTOMER = "Customer"


class ServiceLevel(str, Enum):
    THRESHOLD = "THRESHOLD"
    ROOM_OF_CHOICE = "ROOM_OF_CHOICE"
    WHITE_GLOVE = "WHITE_GLOVE"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    ROUTED = "ROUTED"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    REFUSED_RETRY = "REFUSED_RETRY"
    SETTLED = "SETTLED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class WindowStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class RouteStatus(str, Enum):
    PLANNING = "PLANNING"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"


class DockStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DockAppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class TeamStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class AttemptOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    REFUSED = "REFUSED"
    CUSTOMER_UNAVAILABLE = "CUSTOMER_UNAVAILABLE"
    DAMAGED = "DAMAGED"


class DamageSeverity(str, Enum):
    NONE = "NONE"
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class Placement(str, Enum):
    THRESHOLD = "THRESHOLD"
    ROOM_OF_CHOICE = "ROOM_OF_CHOICE"
    WHITE_GLOVE = "WHITE_GLOVE"


# --- Entity shapes (common_fields: true carry id/created_at/updated_at/version) ---

class Depot(TypedDict):
    id: str
    name: str
    region_code: str
    created_at: str
    updated_at: str
    version: int


class Dock(TypedDict):
    id: str
    depot_id: str
    dock_code: str
    slot_length_min: int
    buffer_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryTeam(TypedDict):
    id: str
    depot_id: str
    team_name: str
    lead_name: str
    member2_name: str
    region_code: str
    max_daily_stops: int
    max_daily_weight_lbs: int
    max_daily_volume_cuft: int
    white_glove_certified: bool
    assembly_certified: bool
    status: str
    estimated_liability_points: int
    settled_liability_points: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    full_name: str
    address_line: str
    region_code: str
    geo_lat: float
    geo_lng: float
    outstanding_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict):
    id: str
    customer_id: str
    item_description: str
    weight_lbs: float
    volume_cuft: float
    declared_value_cents: int
    service_level: str
    assembly_required: bool
    haul_away_required: bool
    stair_flights: int
    status: str
    reattempt_count: int
    active_window_id: Optional[str]
    active_stop_id: Optional[str]
    actual_placement_level: Optional[str]
    quoted_fee_cents: int
    final_fee_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DeliveryWindow(TypedDict):
    id: str
    order_id: str
    team_id: str
    service_date: str
    window_start_min: int
    window_end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    depot_id: str
    team_id: str
    service_date: str
    status: str
    dock_appointment_id: Optional[str]
    dock_ready: bool
    committed_stops: int
    committed_weight_lbs: float
    committed_volume_cuft: float
    route_settlement_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    order_id: str
    window_id: str
    sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DockAppointment(TypedDict):
    id: str
    dock_id: str
    route_id: str
    appt_date: str
    appt_start_min: int
    appt_end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only record (common_fields: false → only id + created_at) ---

class DeliveryAttempt(TypedDict):
    id: str
    order_id: str
    stop_id: str
    attempt_number: int
    outcome: str
    refusal_reason: Optional[str]
    damage_severity: str
    placement: Optional[str]
    signature_captured: bool
    photo_count: int
    assembly_completed: bool
    debris_weight_lbs: float
    fee_delta_cents: int
    created_at: str
