"""Domain types: entity TypedDicts, status enums, role enum.

All field names are exact as stated in the PRD. Two entities (TankMonitorReading,
DegreeDayReading) are immutable observations carrying only id + created_at; their
TypedDicts deliberately omit updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    ACCOUNT_MANAGER = "AccountManager"
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    INSPECTOR = "Inspector"
    CUSTOMER = "Customer"
    SYSTEM = "System"


# --- Enums ---
class FuelType(str, Enum):
    PROPANE = "PROPANE"
    HEATING_OIL = "HEATING_OIL"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PlanType(str, Enum):
    FIXED = "FIXED"
    CAP = "CAP"
    MARKET = "MARKET"


class PricePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class DeliveryMode(str, Enum):
    WILL_CALL = "WILL_CALL"
    AUTOMATIC = "AUTOMATIC"


class TankServiceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    LOCKED_OUT = "LOCKED_OUT"
    DECOMMISSIONED = "DECOMMISSIONED"


class ReorderStatus(str, Enum):
    OK = "OK"
    DUE = "DUE"


class MarketPriceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class TankLeaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class InspectionResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class RouteStatus(str, Enum):
    PLANNING = "PLANNING"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderOrigin(str, Enum):
    WILL_CALL = "WILL_CALL"
    AUTOMATIC = "AUTOMATIC"


class OrderPriority(str, Enum):
    STANDARD = "STANDARD"
    EMERGENCY = "EMERGENCY"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    SCHEDULED = "SCHEDULED"
    HOLD = "HOLD"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BudgetPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RECONCILED = "RECONCILED"


# --- Entity TypedDicts (common_fields: true -> id, created_at, updated_at, version) ---
class Account(TypedDict):
    id: str
    customer_name: str
    region_code: str
    fuel_type: str
    service_status: str
    credit_balance_cents: int
    active_price_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PricePlan(TypedDict):
    id: str
    account_id: str
    plan_type: str
    locked_price_cents_per_gallon: Optional[int]
    cap_price_cents_per_gallon: Optional[int]
    status: str
    effective_from: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Tank(TypedDict):
    id: str
    account_id: str
    capacity_gallons: int
    current_gallons: int
    reorder_threshold_pct: int
    k_factor: int
    delivery_mode: str
    monitor_installed: bool
    last_delivery_at: Optional[str]
    last_reading_at: Optional[str]
    service_status: str
    reorder_status: str
    created_at: str
    updated_at: str
    version: int


class MarketPrice(TypedDict):
    id: str
    region_code: str
    fuel_type: str
    market_price_cents_per_gallon: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TankLease(TypedDict):
    id: str
    tank_id: str
    monthly_rent_cents: int
    lease_start: str
    lease_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyInspection(TypedDict):
    id: str
    tank_id: str
    result: str
    inspected_at: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    region_code: str
    daily_capacity_gallons: int
    turnaround_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict):
    id: str
    truck_id: str
    route_date: str
    window_start: str
    window_end: str
    status: str
    reserved_gallons: int
    created_at: str
    updated_at: str
    version: int


class DeliveryOrder(TypedDict):
    id: str
    account_id: str
    tank_id: str
    route_id: Optional[str]
    origin: str
    requested_gallons: int
    priority: str
    status: str
    delivered_gallons: Optional[int]
    price_cents_per_gallon: Optional[int]
    invoice_total_cents: Optional[int]
    budget_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BudgetPlan(TypedDict):
    id: str
    account_id: str
    plan_year_start: str
    estimated_annual_gallons: int
    estimated_price_cents_per_gallon: int
    monthly_installment_cents: Optional[int]
    installments_paid_count: int
    actual_cost_to_date_cents: int
    status: str
    settlement_balance_cents: int
    created_at: str
    updated_at: str
    version: int


# --- Immutable observations (common_fields: false -> id + created_at only) ---
class TankMonitorReading(TypedDict):
    id: str
    tank_id: str
    reading_gallons: int
    read_at: str
    created_at: str


class DegreeDayReading(TypedDict):
    id: str
    region_code: str
    reading_date: str
    heating_degree_days: int
    created_at: str
