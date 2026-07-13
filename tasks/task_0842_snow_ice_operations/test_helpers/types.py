"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --- Enums -----------------------------------------------------------------

class UserRole(str, Enum):
    DISPATCH_SUPERVISOR = "DispatchSupervisor"
    OPERATOR = "Operator"
    YARD_MANAGER = "YardManager"
    CITIZEN_SERVICES = "CitizenServices"


class VehicleType(str, Enum):
    PLOW = "PLOW"
    SPREADER = "SPREADER"
    COMBO = "COMBO"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CdlClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class RouteTier(str, Enum):
    ARTERIAL = "ARTERIAL"
    RESIDENTIAL = "RESIDENTIAL"


class StormSeverity(str, Enum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"
    EMERGENCY = "EMERGENCY"


class OperationalStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class BillingStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class AssignmentType(str, Enum):
    PRETREAT = "PRETREAT"
    PLOWING = "PLOWING"


class AssignmentStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class MaterialType(str, Enum):
    SALT = "SALT"
    BRINE = "BRINE"


class ApplicationStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class PayMode(str, Enum):
    STANDARD = "STANDARD"
    STORM_MODE = "STORM_MODE"


class CalloutStatus(str, Enum):
    ISSUED = "ISSUED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ComplaintType(str, Enum):
    MISSED_STREET = "MISSED_STREET"
    ICY_CONDITIONS = "ICY_CONDITIONS"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class CostVariant(str, Enum):
    ESTIMATE = "ESTIMATE"
    ACTUAL = "ACTUAL"


# --- Entity TypedDicts -----------------------------------------------------
# Entities carrying the full common set: id, created_at, updated_at, version.

class Depot(TypedDict):
    id: str
    name: str
    salt_tons_on_hand: float
    brine_gallons_on_hand: float
    initial_salt_tons: float
    initial_brine_gallons: float
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    home_depot_id: str
    unit_number: str
    vehicle_type: str
    has_spreader: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict):
    id: str
    full_name: str
    badge_number: str
    cdl_class: str
    hourly_rate_cents: int
    regular_hours_accrued: float
    overtime_hours_accrued: float
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    name: str
    tier: str
    lane_miles: float
    zone: str
    created_at: str
    updated_at: str
    version: int


class StormEvent(TypedDict):
    id: str
    name: str
    severity: str
    forecast_start_at: str
    forecast_end_at: str
    operational_status: str
    billing_status: str
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteAssignment(TypedDict):
    id: str
    storm_event_id: str
    route_id: str
    vehicle_id: str
    operator_id: str
    assignment_type: str
    window_start_at: str
    window_end_at: str
    planned_material_tons: float
    status: str
    last_lat: Optional[float]
    last_lon: Optional[float]
    last_ping_at: Optional[str]
    plow_down: bool
    created_at: str
    updated_at: str
    version: int


class MaterialApplication(TypedDict):
    id: str
    route_assignment_id: str
    depot_id: str
    material_type: str
    salt_tons: float
    brine_gallons: float
    lane_miles_treated: float
    pavement_temp_f: float
    recommended_salt_tons: float
    applied_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Callout(TypedDict):
    id: str
    storm_event_id: str
    operator_id: str
    window_start_at: str
    window_end_at: str
    hours_worked: float
    pay_mode: Optional[str]
    regular_hours: float
    overtime_hours: float
    pay_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    route_id: str
    storm_event_id: str
    address: str
    complaint_type: str
    missed_street_confirmed: bool
    reported_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable snapshot, carries ONLY id + created_at.
class CostReport(TypedDict):
    id: str
    storm_event_id: str
    variant: str
    total_material_cost_cents: int
    total_labor_cost_cents: int
    total_cost_cents: int
    generated_at: str
    created_at: str
