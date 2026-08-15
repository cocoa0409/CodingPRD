"""Domain types: entity TypedDicts, status enums, role enum.

Per PRD section 2.4, all top-level resources carry id/created_at/updated_at/version.
The two append-only sub-resources (AssignmentCharge, TelematicsReading) carry only
id and created_at -- both updated_at and version are absent on them.
"""
from enum import Enum
from typing import Optional, TypedDict


class AvailabilityStatus(str, Enum):
    IDLE = "IDLE"
    RESERVED = "RESERVED"
    ON_RENT = "ON_RENT"
    IN_TRANSIT = "IN_TRANSIT"
    DOWN = "DOWN"
    DISPOSED = "DISPOSED"


class MaintenanceStatus(str, Enum):
    SERVICE_OK = "SERVICE_OK"
    SERVICE_DUE = "SERVICE_DUE"
    IN_SERVICE = "IN_SERVICE"


class ProjectStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CloseReason(str, Enum):
    COMPLETED = "COMPLETED"
    EARLY_RETURN = "EARLY_RETURN"
    EQUIPMENT_DOWN = "EQUIPMENT_DOWN"
    PROJECT_CLOSED = "PROJECT_CLOSED"
    REDEPLOYED = "REDEPLOYED"


class WorkOrderStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkOrderKind(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    REPAIR = "REPAIR"


class MechanicStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_JOB = "ON_JOB"
    OFF_DUTY = "OFF_DUTY"


class TransportStatus(str, Enum):
    PLANNED = "PLANNED"
    EN_ROUTE = "EN_ROUTE"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class LowboyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_HAUL = "ON_Haul"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ReadingStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    VOIDED = "VOIDED"


class DamageStatus(str, Enum):
    FILED = "FILED"
    ASSESSED = "ASSESSED"
    DISPUTED = "DISPUTED"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class Ownership(str, Enum):
    OWNED = "OWNED"
    RENTED = "RENTED"


class CheaperVariant(str, Enum):
    OWN = "OWN"
    RENT = "RENT"
    TIE = "TIE"


class DisposalMethod(str, Enum):
    SALE = "SALE"
    SCRAP = "SCRAP"


class UserRole(str, Enum):
    FLEET_ADMIN = "FleetAdmin"
    PROJECT_MANAGER = "ProjectManager"
    MECHANIC = "Mechanic"
    DISPATCHER = "Dispatcher"


# --- Entity TypedDicts (common_fields: true -> id + created_at + updated_at + version) ---

class EquipmentClass(TypedDict, total=False):
    id: str
    class_code: str
    daily_rate_cents: int
    external_daily_rate_cents: int
    weekend_multiplier_bp: int
    idle_day_multiplier_bp: int
    service_interval_hours: int
    idle_alert_utilization_bp: int
    expected_life_hours: int
    salvage_value_cents: int
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict, total=False):
    id: str
    unit_tag: str
    class_id: str
    ownership: str
    acquisition_cost_cents: int
    acquisition_date: str
    useful_life_months: int
    availability_status: str
    maintenance_status: str
    engine_hours_milli: int
    hours_at_last_service_milli: int
    hours_since_service_milli: int
    current_project_id: Optional[str]
    current_site_id: Optional[str]
    disposed_at: Optional[str]
    residual_value_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    project_code: str
    name: str
    status: str
    equipment_budget_cents: int
    billed_total_cents: int
    active_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    equipment_id: str
    project_id: str
    start_date: str
    end_date: str
    status: str
    activated_at: Optional[str]
    closed_at: Optional[str]
    billable_days: int
    idle_days: int
    engine_hours_billed_milli: int
    utilization_elapsed_bp: Optional[int]
    utilization_billing_bp: Optional[int]
    close_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false -- append-only ledger row; id + created_at ONLY (no updated_at, no version)
class AssignmentCharge(TypedDict, total=False):
    id: str
    assignment_id: str
    project_id: str
    allocated_cents: int
    own_cost_cents: int
    rent_cost_cents: int
    cheaper_variant: str
    created_at: str


class WorkOrder(TypedDict, total=False):
    id: str
    equipment_id: str
    kind: str
    status: str
    trigger_hours_milli: int
    mechanic_id: Optional[str]
    dispatched_at: Optional[str]
    completed_at: Optional[str]
    notes: str
    created_at: str
    updated_at: str
    version: int


class Mechanic(TypedDict, total=False):
    id: str
    mechanic_code: str
    name: str
    status: str
    home_project_id: str
    active_work_order_count: int
    created_at: str
    updated_at: str
    version: int


class TransportJob(TypedDict, total=False):
    id: str
    equipment_id: str
    from_project_id: str
    to_project_id: str
    lowboy_id: str
    depart_at: str
    arrive_at: str
    status: str
    assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lowboy(TypedDict, total=False):
    id: str
    lowboy_code: str
    status: str
    capacity_units: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false -- append-only; id + created_at ONLY
class TelematicsReading(TypedDict, total=False):
    id: str
    equipment_id: str
    recorded_date: str
    engine_hours_delta_milli: int
    fuel_used_milliliters: int
    status: str
    void_reason: Optional[str]
    created_at: str


class DamageReport(TypedDict, total=False):
    id: str
    equipment_id: str
    project_id: str
    description: str
    abuse_flag: bool
    line_items: list
    status: str
    assessed_charge_cents: Optional[int]
    confirmed_charge_cents: Optional[int]
    dispute_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
