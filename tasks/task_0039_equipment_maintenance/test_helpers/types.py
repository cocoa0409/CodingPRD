"""Domain types: entity TypedDicts, status enums, role enum.

Derived from PRD §2.4, §3.2–§3.8. Entities split by whether they carry the
common quartet (id, created_at, updated_at, version) — PRD §2.4 lists
TaskTemplate, RepairRecord, AlarmEvent, AuditEntry as exempt from updated_at
and version.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    SITE_MANAGER = "SiteManager"
    PLAN_OWNER = "PlanOwner"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    STOREKEEPER = "Storekeeper"


# ---------------------------------------------------------------------------
# Status enums (PRD §3.2–§3.8)
# ---------------------------------------------------------------------------
class EquipmentLifecycleStatus(str, Enum):
    INSTALLED = "INSTALLED"
    COMMISSIONED = "COMMISSIONED"
    IN_SERVICE = "IN_SERVICE"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class EquipmentCategory(str, Enum):
    PUMP = "PUMP"
    COMPRESSOR = "COMPRESSOR"
    HVAC = "HVAC"
    CONVEYOR = "CONVEYOR"
    BOILER = "BOILER"


class EquipmentCriticality(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TaskTemplateSkill(str, Enum):
    MECHANICAL = "MECHANICAL"
    ELECTRICAL = "ELECTRICAL"
    HYDRAULIC = "HYDRAULIC"
    HVAC_CERT = "HVAC_CERT"
    CONTROLS = "CONTROLS"


class TaskPriority(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
    P4 = "P4"


class PlanKind(str, Enum):
    PERIODIC_TIME = "PERIODIC_TIME"
    PERIODIC_USAGE = "PERIODIC_USAGE"
    TRIGGER_ALARM = "TRIGGER_ALARM"
    TRIGGER_THRESHOLD = "TRIGGER_THRESHOLD"


class ThresholdOp(str, Enum):
    GTE = "GTE"
    GT = "GT"
    LTE = "LTE"
    LT = "LT"


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFF_DUTY = "OFF_DUTY"


class WorkOrderStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WorkOrderSource(str, Enum):
    PLAN_PERIODIC = "PLAN_PERIODIC"
    PLAN_TRIGGER = "PLAN_TRIGGER"
    ALARM = "ALARM"
    AD_HOC = "AD_HOC"


class PauseReason(str, Enum):
    WAIT_PARTS = "WAIT_PARTS"
    WAIT_VENDOR = "WAIT_VENDOR"
    WAIT_INFO = "WAIT_INFO"


class RequisitionStatus(str, Enum):
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    CANCELLED = "CANCELLED"


class AlarmSeverity(str, Enum):
    INFO = "INFO"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class AuditAction(str, Enum):
    WORK_ORDER_STATE_CHANGE = "WORK_ORDER_STATE_CHANGE"
    PARTS_ISSUED = "PARTS_ISSUED"
    PARTS_RETURNED = "PARTS_RETURNED"
    TECHNICIAN_ASSIGNED = "TECHNICIAN_ASSIGNED"


# ---------------------------------------------------------------------------
# Entity TypedDicts.
# Common-fields entities (PRD §2.4): Site, Equipment, MaintenancePlan,
# SparePart, Technician, WorkOrder, Requisition. Append-only entities (no
# updated_at, no version): TaskTemplate, RepairRecord, AlarmEvent, AuditEntry.
# ---------------------------------------------------------------------------
class Site(TypedDict, total=False):
    id: str
    name: str
    clock_now: str
    sweep_run_index: int
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict, total=False):
    id: str
    site_id: str
    asset_tag: str
    category: str
    location: str
    responsible_user_id: str
    technical_spec: dict
    criticality: str
    warranty_start: str
    warranty_end: str
    lifecycle_status: str
    usage_counter: int
    last_failure_at: Optional[str]
    last_repair_completed_at: Optional[str]
    open_work_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TaskTemplate(TypedDict, total=False):
    id: str
    site_id: str
    code: str
    title: str
    equipment_category: str
    required_skill: str
    estimated_minutes: int
    default_priority: str
    created_at: str


class MaintenancePlan(TypedDict, total=False):
    id: str
    site_id: str
    equipment_id: str
    template_id: str
    kind: str
    interval_days: Optional[int]
    interval_usage: Optional[int]
    alarm_code: Optional[str]
    threshold_metric: Optional[str]
    threshold_op: Optional[str]
    threshold_value: Optional[float]
    status: str
    last_generated_at: Optional[str]
    last_generated_usage: Optional[int]
    next_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SparePart(TypedDict, total=False):
    id: str
    site_id: str
    sku: str
    name: str
    unit_cost_cents: int
    stock_on_hand: int
    stock_reserved: int
    reorder_point: int
    replenish_pending: bool
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    site_id: str
    name: str
    skills: List[str]
    status: str
    open_load: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    site_id: str
    equipment_id: str
    template_id: str
    plan_id: Optional[str]
    source: str
    priority: str
    priority_score: int
    required_skill: str
    estimated_minutes: int
    assigned_technician_id: Optional[str]
    status: str
    opened_at: str
    started_at: Optional[str]
    completed_at: Optional[str]
    closed_at: Optional[str]
    sla_due_at: str
    sla_breached: bool
    pause_reason: Optional[str]
    total_active_minutes: int
    parts_cost_cents: Optional[int]
    reassign_count: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Requisition(TypedDict, total=False):
    id: str
    work_order_id: str
    part_id: str
    qty: int
    status: str
    unit_cost_cents_at_issue: Optional[int]
    returned_qty: int
    created_at: str
    updated_at: str
    version: int


class RepairRecord(TypedDict, total=False):
    id: str
    work_order_id: str
    fault_description: str
    root_cause: str
    repair_actions: str
    working_minutes: int
    before_evidence_url: str
    after_evidence_url: str
    parts_replaced: list
    acceptance_user_id: Optional[str]
    acceptance_at: Optional[str]
    created_at: str


class AlarmEvent(TypedDict, total=False):
    id: str
    equipment_id: str
    alarm_code: str
    severity: str
    emitted_at: str
    generated_work_order_id: Optional[str]
    created_at: str


class AuditEntry(TypedDict, total=False):
    id: str
    site_id: str
    actor_role: str
    actor_user_id: str
    action: str
    target_id: str
    from_value: str
    to_value: str
    occurred_at: str
    created_at: str


__all__ = [
    "UserRole",
    "EquipmentLifecycleStatus",
    "EquipmentCategory",
    "EquipmentCriticality",
    "TaskTemplateSkill",
    "TaskPriority",
    "PlanKind",
    "ThresholdOp",
    "PlanStatus",
    "TechnicianStatus",
    "WorkOrderStatus",
    "WorkOrderSource",
    "PauseReason",
    "RequisitionStatus",
    "AlarmSeverity",
    "AuditAction",
    "Site",
    "Equipment",
    "TaskTemplate",
    "MaintenancePlan",
    "SparePart",
    "Technician",
    "WorkOrder",
    "Requisition",
    "RepairRecord",
    "AlarmEvent",
    "AuditEntry",
]
