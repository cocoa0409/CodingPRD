"""Domain types: entity TypedDicts, status enums, role enum for the Mobile Fuel Delivery API."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enums ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    FLEET_MANAGER = "FleetManager"
    MEMBER = "Member"
    BILLING_OFFICER = "BillingOfficer"


class CustomerType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FLEET = "FLEET"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class FleetAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class TruckStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_ROUTE = "ON_ROUTE"
    MAINTENANCE = "MAINTENANCE"


class RouteStatus(str, Enum):
    PLANNING = "PLANNING"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ROUTED = "ROUTED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    DELIVERED = "DELIVERED"
    UNABLE_TO_ACCESS = "UNABLE_TO_ACCESS"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNCHARGED = "UNCHARGED"
    CHARGED = "CHARGED"


class FuelType(str, Enum):
    REGULAR = "REGULAR"
    PREMIUM = "PREMIUM"
    DIESEL = "DIESEL"


class Zone(str, Enum):
    ZONE_A = "ZONE_A"
    ZONE_B = "ZONE_B"


class AddOnType(str, Enum):
    CAR_WASH = "CAR_WASH"
    OIL_CHANGE = "OIL_CHANGE"


# ─── Entities carrying common fields (id, created_at, updated_at, version) ──

class Customer(TypedDict):
    id: str
    name: str
    email: str
    customer_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    customer_id: str
    tier: str
    monthly_fee_cents: int
    included_deliveries: int
    price_lock_enabled: bool
    deliveries_used_this_period: int
    status: str
    current_period_start: str
    current_period_end: str
    estimated_next_charge_cents: int
    final_settlement_charge_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FleetAccount(TypedDict):
    id: str
    customer_id: str
    monthly_budget_cap_cents: int
    allowed_fuel_types: List[str]
    allowed_addons: List[str]
    committed_budget_cents: int
    settled_budget_cents: int
    remaining_budget_cents: int
    active_vehicle_count: int
    suspended_vehicle_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    customer_id: str
    fleet_account_id: Optional[str]
    make_model: str
    fuel_type: str
    tank_capacity_gallons: float
    current_fuel_level_gallons: float
    monthly_spend_cap_cents: int
    committed_spend_cents: int
    settled_spend_cents: int
    remaining_budget_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FuelTruck(TypedDict):
    id: str
    plate: str
    home_zone: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TruckCompartment(TypedDict):
    id: str
    truck_id: str
    fuel_type: str
    gallons_capacity: float
    gallons_onboard: float
    gallons_reserved: float
    gallons_available: float
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    truck_id: str
    assigned_driver_id: str
    zone: str
    window_start: str
    window_end: str
    max_stops: int
    stop_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict):
    id: str
    customer_id: str
    vehicle_id: str
    membership_id: Optional[str]
    fleet_account_id: Optional[str]
    route_id: Optional[str]
    fuel_type: str
    zone: str
    delivery_address: str
    requested_gallons: float
    is_priority: bool
    delivery_window_start: str
    delivery_window_end: str
    dispensed_gallons: Optional[float]
    locked_price_per_gallon_cents: int
    estimated_fuel_cost_cents: int
    final_fuel_cost_cents: Optional[int]
    service_fee_cents: int
    addon_total_cents: int
    membership_discount_cents: int
    estimated_total_cents: int
    total_cost_cents: Optional[int]
    payment_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Lightweight records (id + created_at only; no updated_at, no version) ──

class AddOnService(TypedDict):
    id: str
    order_id: str
    addon_type: str
    list_price_cents: int
    charged_price_cents: int
    created_at: str


class FuelPrice(TypedDict):
    id: str
    fuel_type: str
    zone: str
    price_per_gallon_cents: int
    effective_date: str
    created_at: str
