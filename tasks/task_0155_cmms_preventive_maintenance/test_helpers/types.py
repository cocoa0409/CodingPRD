"""Domain types: entity TypedDicts, status enums, role enum.

All names are PRD-exact. MeterReading is the only entity without
updated_at/version (it is immutable once recorded, per PRD §2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Enums -----------------------------------------------------------------

class UserRole(str, Enum):
    MAINTENANCE_MANAGER = "MaintenanceManager"
    PLANNER = "Planner"
    TECHNICIAN = "Technician"
    INVENTORY_CLERK = "InventoryClerk"
    WARRANTY_ADMIN = "WarrantyAdmin"


class Criticality(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class MeterUnit(str, Enum):
    HOURS = "HOURS"
    CYCLES = "CYCLES"
    KM = "KM"


class AssetStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DOWN = "DOWN"
    RETIRED = "RETIRED"


class Severity(str, Enum):
    ROUTINE = "ROUTINE"
    MAJOR = "MAJOR"
    OVERHAUL = "OVERHAUL"


class SkillLevel(str, Enum):
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"
    MASTER = "MASTER"


class TriggerType(str, Enum):
    METER = "METER"
    CALENDAR = "CALENDAR"


class WoType(str, Enum):
    PREVENTIVE = "PREVENTIVE"
    CORRECTIVE = "CORRECTIVE"


class ExecutionStatus(str, Enum):
    DRAFT = "DRAFT"
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PartsStatus(str, Enum):
    NONE = "NONE"
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class ReasonCode(str, Enum):
    MECHANICAL_FAILURE = "MECHANICAL_FAILURE"
    ELECTRICAL_FAILURE = "ELECTRICAL_FAILURE"
    OPERATOR_ERROR = "OPERATOR_ERROR"
    PLANNED_PM = "PLANNED_PM"
    IDLE = "IDLE"


class DowntimeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class ClaimType(str, Enum):
    REPLACEMENT = "REPLACEMENT"
    REPAIR = "REPAIR"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# --- Entity TypedDicts -----------------------------------------------------
# common_fields: true -> id, created_at, updated_at, version
# MeterReading is common_fields: false -> only id, created_at

class Site(TypedDict):
    id: str
    name: str
    timezone: str
    maintenance_budget_cents: int
    budget_spent_cents: int
    created_at: str
    updated_at: str
    version: int


class SparePart(TypedDict):
    id: str
    sku: str
    name: str
    on_hand_qty: int
    reserved_qty: int
    unit_cost_cents: int
    reorder_point: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    name: str
    skill_level: str
    weekly_capacity_hours: float
    backlog_hours: float
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    site_id: str
    parent_asset_id: Optional[str]
    name: str
    criticality: str
    status: str
    meter_unit: str
    meter_reading: float
    warranty_expires_at: Optional[str]
    warranty_cost_cap_cents: Optional[int]
    acquisition_cost_cents: int
    mtbf_hours: float
    mttr_hours: float
    created_at: str
    updated_at: str
    version: int


class PMSchedule(TypedDict):
    id: str
    asset_id: str
    trigger_type: str
    meter_interval: Optional[float]
    calendar_interval_days: Optional[int]
    estimated_labor_hours: float
    severity: str
    anchor_meter: float
    anchor_date: str
    next_due_meter: Optional[float]
    next_due_date: Optional[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class MeterReading(TypedDict):
    id: str
    asset_id: str
    value: float
    reading_at: str
    triggered_pm: bool
    created_at: str


class WorkOrder(TypedDict):
    id: str
    asset_id: str
    pm_schedule_id: Optional[str]
    assigned_technician_id: Optional[str]
    wo_type: str
    severity: str
    execution_status: str
    parts_status: str
    priority_score: float
    estimated_labor_hours: float
    actual_cost_cents: int
    warranty_claim_id: Optional[str]
    opened_at: Optional[str]
    closed_at: Optional[str]
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartReservation(TypedDict):
    id: str
    work_order_id: str
    spare_part_id: str
    qty: int
    status: str
    committed_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class DowntimeEvent(TypedDict):
    id: str
    asset_id: str
    work_order_id: Optional[str]
    reason_code: str
    started_at: str
    ended_at: Optional[str]
    status: str
    duration_hours: float
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    asset_id: str
    work_order_id: str
    claim_type: str
    claimed_cost_cents: int
    payable_cost_cents: int
    status: str
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int
