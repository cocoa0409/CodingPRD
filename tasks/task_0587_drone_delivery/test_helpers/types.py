"""Domain types for the Drone BVLOS Delivery API: status enums, entity TypedDicts, roles."""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- roles
class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DISPATCH_OPERATOR = "DispatchOperator"
    FLIGHT_DIRECTOR = "FlightDirector"
    MAINTENANCE_TECH = "MaintenanceTech"
    PLATFORM_ADMIN = "PlatformAdmin"


# ------------------------------------------------------------------- status enums
class ServiceAreaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class NestStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DroneStatus(str, Enum):
    IDLE = "IDLE"
    RESERVED = "RESERVED"
    IN_FLIGHT = "IN_FLIGHT"
    GROUNDED = "GROUNDED"


class AirframeClass(str, Enum):
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"


class BatteryState(str, Enum):
    CHARGING = "CHARGING"
    READY = "READY"
    IN_USE = "IN_USE"
    COOLDOWN = "COOLDOWN"
    RETIRED = "RETIRED"


class OrderStatus(str, Enum):
    QUOTED = "QUOTED"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderPriority(str, Enum):
    STANDARD = "STANDARD"
    URGENT = "URGENT"
    MEDICAL = "MEDICAL"


class FlightOpsState(str, Enum):
    PLANNED = "PLANNED"
    LAUNCHED = "LAUNCHED"
    DROPPING = "DROPPING"
    RETURNING = "RETURNING"
    RECOVERED = "RECOVERED"
    ABORTED = "ABORTED"


class FlightClearanceState(str, Enum):
    UNFILED = "UNFILED"
    FILED = "FILED"
    CLEARED = "CLEARED"
    REVOKED = "REVOKED"


class AbortReason(str, Enum):
    OPERATOR = "OPERATOR"
    DRONE_GROUNDED = "DRONE_GROUNDED"
    WEATHER = "WEATHER"


class AuthorizationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"


class GeofenceKind(str, Enum):
    NO_FLY = "NO_FLY"
    TFR = "TFR"
    WEATHER_HOLD = "WEATHER_HOLD"


class GeofenceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class Precip(str, Enum):
    NONE = "NONE"
    LIGHT = "LIGHT"
    HEAVY = "HEAVY"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentCategory(str, Enum):
    HARD_LANDING = "HARD_LANDING"
    LOST_LINK = "LOST_LINK"
    PAYLOAD_RELEASE = "PAYLOAD_RELEASE"
    AIRSPACE_DEVIATION = "AIRSPACE_DEVIATION"
    GROUND_DAMAGE = "GROUND_DAMAGE"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    MAINTENANCE_REQUIRED = "MAINTENANCE_REQUIRED"
    CLOSED = "CLOSED"


class IncidentOutcome(str, Enum):
    NO_ACTION = "NO_ACTION"
    MAINTENANCE_REQUIRED = "MAINTENANCE_REQUIRED"


class WorkType(str, Enum):
    INSPECTION = "INSPECTION"
    REPAIR = "REPAIR"
    BATTERY_SWAP = "BATTERY_SWAP"
    OVERHAUL = "OVERHAUL"


class MaintenanceLogStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class LaancOutcome(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# --------------------------------------------------------------- entity TypedDicts
# Resources below carry id + created_at + updated_at + version.
class ServiceArea(TypedDict):
    id: str
    name: str
    center_lat: float
    center_lon: float
    max_range_km: float
    max_payload_g: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Nest(TypedDict):
    id: str
    service_area_id: str
    name: str
    lat: float
    lon: float
    pad_count: int
    status: str
    reserved_pads: int
    created_at: str
    updated_at: str
    version: int


class Drone(TypedDict):
    id: str
    home_nest_id: str
    tail_number: str
    airframe_class: str
    max_payload_g: int
    cruise_speed_kmh: float
    hours_since_service: float
    flight_hours: float
    status: str
    installed_battery_id: Optional[str]
    advisory_risk_score: float
    blocking_risk_score: float
    created_at: str
    updated_at: str
    version: int


class Battery(TypedDict):
    id: str
    nest_id: str
    serial: str
    charge_pct: float
    cycle_count: int
    state: str
    health_pct: float
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    email: str
    dropoff_lat: float
    dropoff_lon: float
    held_total: float
    billed_total: float
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    service_area_id: str
    payload_weight_g: int
    priority: str
    dropoff_lat: float
    dropoff_lon: float
    distance_km: float
    delivery_fee: float
    airspace_surcharge: float
    order_total: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict):
    id: str
    order_id: str
    drone_id: str
    launch_nest_id: str
    recovery_nest_id: str
    battery_id: str
    ops_state: str
    clearance_state: str
    planned_route_km: float
    required_energy_pct: float
    actual_energy_pct: Optional[float]
    actual_route_km: Optional[float]
    wind_kph_at_dispatch: float
    eta_recovery_at: str
    pad_hold_start: str
    pad_hold_end: str
    filed_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AirspaceAuthorization(TypedDict):
    id: str
    flight_id: str
    grid_cells: List[str]
    requested_alt_ft: int
    window_start: str
    window_end: str
    status: str
    auth_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GeofenceZone(TypedDict):
    id: str
    service_area_id: str
    kind: str
    center_lat: float
    center_lon: float
    radius_km: float
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict):
    id: str
    drone_id: str
    flight_id: Optional[str]
    severity: str
    category: str
    narrative: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceLog(TypedDict):
    id: str
    drone_id: str
    incident_id: Optional[str]
    work_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    completed_at: Optional[str]
    notes: str
    created_at: str
    updated_at: str
    version: int


# WeatherObservation and DeliveryDrop are immutable after creation: they carry
# id and created_at only — no updated_at and no version.
class WeatherObservation(TypedDict):
    id: str
    service_area_id: str
    observed_at: str
    wind_kph: float
    gust_kph: float
    visibility_km: float
    precip: str
    flyable: bool
    created_at: str


class DeliveryDrop(TypedDict):
    id: str
    flight_id: str
    drop_lat: float
    drop_lon: float
    hover_alt_ft: int
    photo_ref: str
    confirmed_by_user_id: str
    created_at: str
