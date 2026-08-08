"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    FLEET_MANAGER = "FleetManager"
    DEPOT_OPERATOR = "DepotOperator"
    MAINTENANCE_TECH = "MaintenanceTech"
    DRIVER = "Driver"
    FINANCE_MANAGER = "FinanceManager"


class ConnectorType(str, Enum):
    CCS = "CCS"
    CHADEMO = "CHADEMO"
    J1772 = "J1772"
    NACS = "NACS"


class ChargerServiceStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DOWN = "DOWN"


class VehicleStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    GROUNDED = "GROUNDED"


class VehicleReadiness(str, Enum):
    READY = "READY"
    NOT_READY = "NOT_READY"


class ChargeSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"


# --- Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ---

class Depot(TypedDict):
    id: str
    name: str
    max_load_kw: float
    contracted_capacity_kw: float
    demand_rate_cents_per_kw: int
    overage_rate_cents_per_kw: int
    reimbursement_budget_cents: int
    tariff_windows: list
    reserved_load_kw: float
    reimbursement_committed_cents: int
    created_at: str
    updated_at: str
    version: int


class Charger(TypedDict):
    id: str
    depot_id: str
    name: str
    connector_type: str
    max_power_kw: float
    service_status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    depot_id: str
    vin: str
    connector_type: str
    battery_capacity_kwh: float
    efficiency_kwh_per_km: float
    current_soc_pct: float
    odometer_km: float
    status: str
    readiness_status: str
    created_at: str
    updated_at: str
    version: int


class Driver(TypedDict):
    id: str
    depot_id: str
    name: str
    email: str
    home_tariff_cents_per_kwh: int
    created_at: str
    updated_at: str
    version: int


class ChargeSession(TypedDict):
    id: str
    depot_id: str
    charger_id: str
    vehicle_id: str
    scheduled_start: str
    scheduled_end: str
    target_soc_pct: float
    power_kw: float
    start_soc_pct: Optional[float]
    end_soc_pct: Optional[float]
    actual_start: Optional[str]
    actual_end: Optional[str]
    energy_kwh_delivered: float
    estimated_cost_cents: int
    final_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event, only id + created_at
class TelemetryReading(TypedDict):
    id: str
    vehicle_id: str
    soc_pct: float
    odometer_km: float
    reading_time: str
    created_at: str


class MaintenanceWorkOrder(TypedDict):
    id: str
    asset_type: str
    charger_id: Optional[str]
    vehicle_id: Optional[str]
    issue: str
    severity: str
    status: str
    opened_at: str
    resolved_at: Optional[str]
    downtime_minutes: int
    created_at: str
    updated_at: str
    version: int


class RouteAssignment(TypedDict):
    id: str
    depot_id: str
    vehicle_id: str
    driver_id: str
    route_name: str
    distance_km: float
    required_soc_pct: float
    scheduled_departure: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ReimbursementClaim(TypedDict):
    id: str
    driver_id: str
    depot_id: str
    period_month: str
    kwh_claimed: float
    odometer_start: float
    odometer_end: float
    metered_kwh_verified: Optional[float]
    committed_amount_cents: int
    estimated_amount_cents: int
    final_amount_cents: int
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    depot_id: str
    period_month: str
    energy_subtotal_cents: int
    peak_demand_kw: float
    demand_charge_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
