"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the MES PRD §3 entity definitions and §2.4 common-resource rules.
Every entity except TravelerSignoff carries the full id/created_at/updated_at/version
set; TravelerSignoff is append-only (id + created_at only).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────

class ProductType(str, Enum):
    FINISHED_GOOD = "FINISHED_GOOD"
    SUBASSEMBLY = "SUBASSEMBLY"
    RAW_MATERIAL = "RAW_MATERIAL"


class RoutingStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    ARCHIVED = "ARCHIVED"


class MachineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RUNNING = "RUNNING"
    DOWN = "DOWN"


class WorkOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_PROCESS = "IN_PROCESS"
    COMPLETED = "COMPLETED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WorkOrderOperationStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    REWORK = "REWORK"


class ScrapDispositionStatus(str, Enum):
    PENDING = "PENDING"
    SCRAPPED = "SCRAPPED"
    REWORKED = "REWORKED"


class SignoffResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class UserRole(str, Enum):
    ManufacturingEngineer = "ManufacturingEngineer"
    ProductionPlanner = "ProductionPlanner"
    MachineOperator = "MachineOperator"
    QualityInspector = "QualityInspector"
    PlantAdmin = "PlantAdmin"


# ─── Entity TypedDicts (common_fields: true) ──────────

class Product(TypedDict):
    id: str
    sku: str
    name: str
    product_type: str
    unit_cost_cents: int
    lot_controlled: bool
    created_at: str
    updated_at: str
    version: int


class BomLine(TypedDict):
    id: str
    parent_product_id: str
    component_product_id: str
    quantity_per: float
    scrap_factor_pct: float
    created_at: str
    updated_at: str
    version: int


class Routing(TypedDict):
    id: str
    product_id: str
    routing_code: str
    status: str
    operation_count: int
    created_at: str
    updated_at: str
    version: int


class Operation(TypedDict):
    id: str
    routing_id: str
    machine_id: str
    sequence_no: int
    ideal_cycle_time_secs: float
    setup_buffer_secs: int
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    machine_code: str
    work_center: str
    status: str
    planned_production_secs: int
    oee_availability: float
    oee_performance: float
    oee_quality: float
    oee_overall: float
    quality_flagged: bool
    created_at: str
    updated_at: str
    version: int


class MachineRunLog(TypedDict):
    id: str
    machine_id: str
    window_start: str
    window_end: str
    run_time_secs: int
    total_units: int
    good_units: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    product_id: str
    routing_id: str
    order_qty: int
    status: str
    started_qty: int
    completed_qty: int
    scrapped_qty: int
    wip_qty: int
    material_variance_cents: int
    created_at: str
    updated_at: str
    version: int


class ComponentDemand(TypedDict):
    id: str
    work_order_id: str
    component_product_id: str
    required_qty: float
    issued_qty: float
    standard_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class WorkOrderOperation(TypedDict):
    id: str
    work_order_id: str
    operation_id: str
    machine_id: str
    sequence_no: int
    status: str
    units_in: int
    good_qty: int
    scrap_qty: int
    scheduled_start: Optional[str]
    scheduled_end: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict):
    id: str
    product_id: str
    lot_code: str
    on_hand_qty: float
    issued_qty: float
    received_qty: float
    created_at: str
    updated_at: str
    version: int


class LotIssue(TypedDict):
    id: str
    component_demand_id: str
    lot_id: str
    work_order_operation_id: str
    issued_qty: float
    reversed: bool
    created_at: str
    updated_at: str
    version: int


class GenealogyLink(TypedDict):
    id: str
    work_order_id: str
    parent_lot_id: str
    child_lot_id: str
    consumed_qty: float
    created_at: str
    updated_at: str
    version: int


class ScrapDisposition(TypedDict):
    id: str
    work_order_operation_id: str
    quantity: int
    defect_code: str
    status: str
    scrap_cost_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false) ────────
# A TravelerSignoff carries only id + created_at: no updated_at, no version.

class TravelerSignoff(TypedDict):
    id: str
    work_order_operation_id: str
    inspector_user_id: str
    result: str
    signed_at: str
    created_at: str
