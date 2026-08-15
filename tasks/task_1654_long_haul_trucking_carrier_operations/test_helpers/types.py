"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FLEET_ADMIN = "FleetAdmin"
    LOAD_PLANNER = "LoadPlanner"
    DISPATCHER = "Dispatcher"
    SAFETY_OFFICER = "SafetyOfficer"
    PAYROLL_CLERK = "PayrollClerk"
    DRIVER = "Driver"


class PayModel(str, Enum):
    MILEAGE = "MILEAGE"
    PERCENTAGE = "PERCENTAGE"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class DutyStatus(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    SLEEPER = "SLEEPER"
    DRIVING = "DRIVING"
    ON_DUTY = "ON_DUTY"


class TractorStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class LoadStatus(str, Enum):
    TENDERED = "TENDERED"
    SCREENED = "SCREENED"
    ACCEPTED = "ACCEPTED"
    ASSIGNED = "ASSIGNED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class TripStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    AT_PICKUP = "AT_PICKUP"
    IN_TRANSIT = "IN_TRANSIT"
    AT_DELIVERY = "AT_DELIVERY"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CancelReason(str, Enum):
    SAFETY = "SAFETY"
    REASSIGN = "REASSIGN"
    CUSTOMER = "CUSTOMER"


class DutyEventType(str, Enum):
    OFF_DUTY = "OFF_DUTY"
    SLEEPER = "SLEEPER"
    DRIVING = "DRIVING"
    ON_DUTY = "ON_DUTY"


class CheckCallKind(str, Enum):
    ARRIVED_PICKUP = "ARRIVED_PICKUP"
    DEPARTED_PICKUP = "DEPARTED_PICKUP"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED_DELIVERY = "ARRIVED_DELIVERY"
    DELIVERED = "DELIVERED"


class AccessorialType(str, Enum):
    DETENTION_PICKUP = "DETENTION_PICKUP"
    DETENTION_DELIVERY = "DETENTION_DELIVERY"
    LAYOVER = "LAYOVER"
    LUMPER = "LUMPER"
    STOP_OFF = "STOP_OFF"


class AccessorialSource(str, Enum):
    AUTO_DETENTION = "AUTO_DETENTION"
    MANUAL = "MANUAL"


class AccessorialStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    BILLED = "BILLED"
    REJECTED = "REJECTED"


class SafetyEventKind(str, Enum):
    INSPECTION_VIOLATION = "INSPECTION_VIOLATION"
    CRASH_AT_FAULT = "CRASH_AT_FAULT"
    HOS_VIOLATION = "HOS_VIOLATION"


class SafetyEventSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_HOS = "AUTO_HOS"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PAID = "PAID"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


# --- Entity bodies (PRD §2.5 common fields: id/created_at/updated_at/version) ---

class Driver(TypedDict, total=False):
    id: str
    cdl_number: str
    full_name: str
    home_terminal: str
    pay_model: str
    pay_rate_cents_per_mile: Optional[int]
    pay_percentage_bp: Optional[int]
    hired_at: str
    last_home_at: str
    employment_status: str
    duty_status: str
    safety_score: int
    created_at: str
    updated_at: str
    version: int


class Tractor(TypedDict, total=False):
    id: str
    unit_number: str
    home_terminal: str
    status: str
    odometer_miles: int
    current_state_code: str
    tank_capacity_gallons: int
    current_fuel_gallons: int
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict, total=False):
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict, total=False):
    id: str
    origin_state: str
    destination_state: str
    loaded_miles: int
    rpm_floor_cents: int
    created_at: str
    updated_at: str
    version: int


class StateFuelRate(TypedDict, total=False):
    id: str
    state_code: str
    tax_cents_per_gallon: int
    avg_pump_price_cents: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Load(TypedDict, total=False):
    id: str
    customer_id: str
    lane_id: str
    rate_cents: int
    weight_lbs: int
    pickup_appt_at: str
    delivery_appt_at: str
    status: str
    fuel_surcharge_cents: Optional[int]
    projected_margin_cents: Optional[int]
    projected_rpm_cents: Optional[int]
    final_margin_cents: Optional[int]
    total_accessorial_cents: int
    cancellation_fee_cents: Optional[int]
    reassignment_count: int
    created_at: str
    updated_at: str
    version: int


class RouteState(TypedDict):
    state_code: str
    miles: int


class Trip(TypedDict, total=False):
    id: str
    load_id: str
    driver_id: str
    tractor_id: str
    planned_deadhead_miles: int
    planned_start_at: str
    route_states: List[RouteState]
    status: str
    start_odometer_miles: Optional[int]
    actual_miles: Optional[int]
    pay_miles: Optional[int]
    provisional_pay_cents: Optional[int]
    final_pay_cents: Optional[int]
    cancel_reason: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only telemetry (PRD §2.5): id + created_at only; no updated_at/version.
class DutyEvent(TypedDict, total=False):
    id: str
    driver_id: str
    trip_id: Optional[str]
    event_type: str
    occurred_at: str
    at_home: bool
    created_at: str


class CheckCall(TypedDict, total=False):
    id: str
    trip_id: str
    kind: str
    occurred_at: str
    state_code: str
    odometer_miles: int
    created_at: str


class AccessorialCharge(TypedDict, total=False):
    id: str
    load_id: str
    trip_id: Optional[str]
    type: str
    quantity: int
    amount_cents: int
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FuelPurchase(TypedDict, total=False):
    id: str
    trip_id: str
    driver_id: str
    state_code: str
    gallons: int
    pump_price_cents: int
    purchased_at: str
    total_cost_cents: int
    tax_paid_cents: int
    net_effective_price_cents: int
    created_at: str
    updated_at: str
    version: int


class SafetyEvent(TypedDict, total=False):
    id: str
    driver_id: str
    kind: str
    severity_points: int
    occurred_at: str
    source: str
    voided: bool
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    driver_id: str
    period_start: str
    period_end: str
    status: str
    trip_pay_cents: int
    accessorial_share_cents: int
    manual_adjustment_cents: int
    guarantee_top_up_cents: int
    gross_pay_cents: int
    created_by_id: str
    approved_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    load_id: str
    status: str
    linehaul_cents: int
    fuel_surcharge_cents: int
    accessorial_total_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int
