"""Domain types: entity TypedDicts, status enums, role enum for the fleet/motor-pool API."""
from enum import Enum
from typing import TypedDict, Optional, List


class VehicleClass(str, Enum):
    SEDAN = "SEDAN"
    PICKUP = "PICKUP"
    SUV = "SUV"
    HEAVY_TRUCK = "HEAVY_TRUCK"
    VAN = "VAN"


class AssignmentType(str, Enum):
    POOL = "POOL"
    DEPARTMENT_ASSIGNED = "DEPARTMENT_ASSIGNED"


class OperationalStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    IN_SHOP = "IN_SHOP"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class LifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FLAGGED_FOR_REPLACEMENT = "FLAGGED_FOR_REPLACEMENT"
    PENDING_DISPOSAL = "PENDING_DISPOSAL"
    DISPOSED = "DISPOSED"


class ReservationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    CHECKED_OUT = "CHECKED_OUT"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class BayType(str, Enum):
    GENERAL = "GENERAL"
    HEAVY = "HEAVY"
    BODY = "BODY"


class ShopBayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CLOSED = "CLOSED"


class WorkOrderType(str, Enum):
    PM = "PM"
    REPAIR = "REPAIR"
    ACCIDENT_REPAIR = "ACCIDENT_REPAIR"


class WorkOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    AWAITING_PARTS = "AWAITING_PARTS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class AccidentClaimStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    SUBROGATION_PENDING = "SUBROGATION_PENDING"
    RECOVERED = "RECOVERED"
    CLOSED_NO_FAULT = "CLOSED_NO_FAULT"
    WRITTEN_OFF = "WRITTEN_OFF"


class DisposalStatus(str, Enum):
    LISTED = "LISTED"
    BIDDING = "BIDDING"
    SOLD = "SOLD"
    NO_SALE = "NO_SALE"


class ChargebackBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ChargebackStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"
    PAID = "PAID"


class UserRole(str, Enum):
    FleetAdmin = "FleetAdmin"
    MotorPoolClerk = "MotorPoolClerk"
    ShopTech = "ShopTech"
    FinanceOfficer = "FinanceOfficer"
    DepartmentUser = "DepartmentUser"


# ---- common_fields: true (id + created_at + updated_at + version) ----

class Vehicle(TypedDict):
    id: str
    vin: str
    vehicle_class: str
    acquisition_cost_cents: int
    in_service_date: str
    odometer_miles: int
    assignment_type: str
    assigned_department_id: Optional[str]
    operational_status: str
    lifecycle_status: str
    lifetime_maintenance_cents: int
    replacement_score: float
    open_accident_count: int
    lifetime_fuel_cents: int
    cost_per_mile_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Department(TypedDict):
    id: str
    name: str
    cost_center_code: str
    monthly_budget_cents: int
    committed_budget_cents: int
    billed_ytd_cents: int
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    department_id: str
    requested_start: str
    requested_end: str
    driver_name: str
    purpose: str
    assigned_vehicle_id: Optional[str]
    status: str
    estimated_cost_cents: int
    checkout_odometer: Optional[int]
    return_odometer: Optional[int]
    miles_driven: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ShopBay(TypedDict):
    id: str
    name: str
    bay_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    vehicle_id: str
    bay_id: str
    wo_type: str
    scheduled_start: str
    scheduled_end: str
    status: str
    labor_hours: Optional[float]
    labor_rate_cents: int
    parts_cost_cents: int
    total_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AccidentClaim(TypedDict):
    id: str
    vehicle_id: str
    reported_at: str
    at_fault: bool
    estimated_damage_cents: int
    deductible_cents: int
    third_party_liable_pct: float
    status: str
    recovered_cents: int
    outstanding_liable_cents: int
    gross_recoverable_cents: int
    net_recoverable_cents: int
    created_at: str
    updated_at: str
    version: int


class DisposalRecord(TypedDict):
    id: str
    vehicle_id: str
    reserve_price_cents: int
    reconditioning_cost_cents: int
    status: str
    sale_price_cents: Optional[int]
    commission_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    buyer_name: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargebackInvoice(TypedDict):
    id: str
    department_id: str
    period_start: str
    period_end: str
    basis: str
    status: str
    assignment_fee_cents: int
    mileage_charge_cents: int
    fuel_surcharge_cents: int
    idle_penalty_cents: int
    total_cents: int
    disputed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---- common_fields: false (id + created_at only; NO updated_at, NO version) ----

class VehicleClassPolicy(TypedDict):
    id: str
    vehicle_class: str
    assignment_fee_cents_per_month: int
    mileage_tier1_rate_cents: int
    mileage_tier2_rate_cents: int
    mileage_tier_boundary_miles: int
    fuel_surcharge_multiplier: float
    idle_free_minutes: int
    idle_penalty_cents_per_min: int
    replacement_age_years: int
    replacement_mileage: int
    replacement_maint_ratio: float
    created_at: str


class FuelLog(TypedDict):
    id: str
    vehicle_id: str
    reading_at: str
    gallons: float
    fuel_cost_cents: int
    odometer_miles: int
    idle_minutes: int
    engine_hours: float
    created_at: str
