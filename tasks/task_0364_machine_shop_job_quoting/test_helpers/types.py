"""Domain types: entity TypedDicts, status enums, role enum.

Field names are PRD-exact. Entities carrying the standard system-managed quartet
(id, created_at, updated_at, version) are marked accordingly; the lone
configuration entity, InspectionStation, carries only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ──────────────────────────────────────────────────────────
class RFQStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    QUOTED = "QUOTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class RoutingOpStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class WorkOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_PROCESS = "IN_PROCESS"
    COMPLETED = "COMPLETED"
    SHIPPED = "SHIPPED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MaterialLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class LotAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class MachineSlotStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class InspectionStatus(str, Enum):
    OPEN = "OPEN"
    DISPOSITIONED = "DISPOSITIONED"


class ShipmentStatus(str, Enum):
    SHIPPED = "SHIPPED"
    VOIDED = "VOIDED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOIDED = "VOIDED"


# ─── Domain value enums ────────────────────────────────────────────────────
class MaterialSpec(str, Enum):
    AL_6061 = "AL_6061"
    SS_304 = "SS_304"
    TI_6AL4V = "TI_6AL4V"
    BRASS_360 = "BRASS_360"


class ToleranceClass(str, Enum):
    STANDARD = "STANDARD"
    PRECISION = "PRECISION"
    CRITICAL = "CRITICAL"


class MachineClass(str, Enum):
    MILL_3AX = "MILL_3AX"
    MILL_5AX = "MILL_5AX"
    LATHE = "LATHE"


class Incoterm(str, Enum):
    EXW = "EXW"
    FOB = "FOB"
    DDP = "DDP"


class InspectionMode(str, Enum):
    FAI = "FAI"
    IN_PROCESS = "IN_PROCESS"
    FINAL = "FINAL"


class StationSupportsMode(str, Enum):
    FAI = "FAI"
    IN_PROCESS = "IN_PROCESS"
    FINAL = "FINAL"
    ALL = "ALL"


class UserRole(str, Enum):
    ShopAdmin = "ShopAdmin"
    Estimator = "Estimator"
    Scheduler = "Scheduler"
    MaterialController = "MaterialController"
    Inspector = "Inspector"


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ─
class RFQ(TypedDict):
    id: str
    customer_name: str
    customer_id: str
    requested_due_date: str
    incoterm: str
    status: str
    part_line_count: int
    created_at: str
    updated_at: str
    version: int


class PartLine(TypedDict):
    id: str
    rfq_id: str
    part_number: str
    drawing_rev: str
    material_spec: str
    quantity: int
    tolerance_class: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict):
    id: str
    rfq_id: str
    part_line_id: str
    status: str
    material_unit_cost_cents: int
    scrap_allowance_pct: int
    margin_pct: int
    extended_cost_cents: int
    quoted_price_cents: int
    quoted_unit_price_cents: int
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoutingOp(TypedDict):
    id: str
    quote_id: str
    seq: int
    machine_class: str
    estimated_cycle_min: float
    actual_cycle_min: Optional[float]
    setup_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict):
    id: str
    quote_id: str
    part_line_id: str
    qty_ordered: int
    qty_started: int
    qty_in_process: int
    qty_accepted: int
    qty_rework_pending: int
    qty_scrapped: int
    qty_shipped: int
    status: str
    material_allocated: bool
    actual_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class MaterialLot(TypedDict):
    id: str
    material_spec: str
    heat_number: str
    qty_received: int
    unit_cost_cents: int
    received_at: str
    qty_remaining: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LotAllocation(TypedDict):
    id: str
    work_order_id: str
    material_lot_id: str
    qty_allocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MachineSlot(TypedDict):
    id: str
    machine_class: str
    machine_code: str
    routing_op_id: str
    start_min: int
    end_min: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    work_order_id: str
    inspection_station_id: str
    mode: str
    window_start_min: int
    window_end_min: int
    qty_inspected: int
    qty_accepted: int
    qty_rework: int
    qty_scrap: int
    status: str
    first_pass_yield_pct: float
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    work_order_id: str
    qty_shipped: int
    promised_date: str
    actual_ship_date: str
    on_time: bool
    days_late: int
    late_penalty_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    shipment_id: str
    work_order_id: str
    subtotal_cents: int
    tax_cents: int
    penalty_credit_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Configuration entity (common_fields: false → id + created_at only) ─────
class InspectionStation(TypedDict):
    id: str
    name: str
    supports_mode: str
    buffer_min: int
    created_at: str
