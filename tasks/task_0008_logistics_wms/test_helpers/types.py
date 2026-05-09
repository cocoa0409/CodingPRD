"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    WAREHOUSE_STAFF = "WarehouseStaff"
    AUDITOR = "Auditor"
    WAREHOUSE_MANAGER = "WarehouseManager"


class WarehousePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class PutawayStrategy(str, Enum):
    DISTANCE_OPTIMIZED = "DISTANCE_OPTIMIZED"
    CAPACITY_OPTIMIZED = "CAPACITY_OPTIMIZED"


class BinZone(str, Enum):
    AMBIENT = "AMBIENT"
    COLD = "COLD"
    HAZMAT = "HAZMAT"
    RETURNS = "RETURNS"


class BinStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class LotCategory(str, Enum):
    AMBIENT = "AMBIENT"
    COLD = "COLD"
    HAZMAT = "HAZMAT"
    RETURNS = "RETURNS"


class LotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NEAR_EXPIRY = "NEAR_EXPIRY"
    EXPIRED = "EXPIRED"
    QUARANTINED = "QUARANTINED"
    RECALLED = "RECALLED"
    DISPOSED = "DISPOSED"


class RecallReason(str, Enum):
    SUPPLIER_RECALL = "SUPPLIER_RECALL"
    SAFETY_ISSUE = "SAFETY_ISSUE"
    EXPIRY_BATCH = "EXPIRY_BATCH"


class InboundShipmentStatus(str, Enum):
    ASN_RECEIVED = "ASN_RECEIVED"
    INSPECTING = "INSPECTING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    PUTAWAY = "PUTAWAY"
    QUARANTINED = "QUARANTINED"
    CLOSED = "CLOSED"


class InboundLineStatus(str, Enum):
    PENDING_INSPECTION = "PENDING_INSPECTION"
    INSPECTED_PASS = "INSPECTED_PASS"
    INSPECTED_FAIL = "INSPECTED_FAIL"
    PUTAWAY = "PUTAWAY"
    QUARANTINED = "QUARANTINED"


class WaveStrategy(str, Enum):
    BATCH = "BATCH"
    ZONE = "ZONE"
    ORDER = "ORDER"


class WaveStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    CREATED = "CREATED"
    ALLOCATED = "ALLOCATED"
    PICKING = "PICKING"
    PICKED = "PICKED"
    SHORT_PICKED = "SHORT_PICKED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class OrderCarrier(str, Enum):
    UPS = "UPS"
    FEDEX = "FEDEX"
    USPS = "USPS"


class PickStrategy(str, Enum):
    FEFO = "FEFO"
    FIFO = "FIFO"


class PickTaskStatus(str, Enum):
    CREATED = "CREATED"
    PICKING = "PICKING"
    PICKED = "PICKED"
    SHORT_PICKED = "SHORT_PICKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CycleCountStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COUNTING = "COUNTING"
    RECONCILED = "RECONCILED"
    VARIANCE_FOUND = "VARIANCE_FOUND"
    ADJUSTED = "ADJUSTED"
    DISPUTED = "DISPUTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class Warehouse(TypedDict, total=False):
    id: str
    name: str
    dock_position_x: int
    dock_position_y: int
    putaway_strategy: str
    ops_run_index: int
    clock_now: str
    shrinkage_value_30d_cents: int
    abnormal_event_count_24h: int
    recall_count_open: int
    risk_score: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class Bin(TypedDict, total=False):
    id: str
    warehouse_id: str
    bin_code: str
    zone: str
    position_x: int
    position_y: int
    capacity_volume_cm3: int
    capacity_weight_g: int
    used_volume_cm3: int
    used_weight_g: int
    remaining_volume_cm3: int
    remaining_weight_g: int
    status: str
    frozen_by_cycle_count_id: Optional[str]
    distance_from_dock: float
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    warehouse_id: str
    lot_code: str
    sku: str
    category: str
    unit_weight_g: int
    unit_volume_cm3: int
    unit_value_cents: int
    manufacture_date: str
    expiry_date: str
    received_at: Optional[str]
    supplier_lot_ref: str
    status: str
    recalled_at: Optional[str]
    recall_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InboundLine(TypedDict, total=False):
    id: str
    inbound_shipment_id: str
    lot_id: str
    declared_units: int
    received_units: Optional[int]
    bin_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InboundShipment(TypedDict, total=False):
    id: str
    warehouse_id: str
    asn_number: str
    supplier_name: str
    declared_total_units: int
    inspection_sample_size: Optional[int]
    inspection_defect_count: Optional[int]
    defect_rate: Optional[float]
    status: str
    lines: List[InboundLine]
    created_at: str
    updated_at: str
    version: int


class Inventory(TypedDict, total=False):
    id: str
    warehouse_id: str
    bin_id: str
    lot_id: str
    qty_units: int
    reserved_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class PickTask(TypedDict, total=False):
    id: str
    order_id: str
    wave_id: Optional[str]
    bin_id: str
    lot_id: str
    inventory_id: str
    planned_units: int
    picked_units: int
    sequence: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    warehouse_id: str
    order_number: str
    customer_name: str
    requested_lines: list
    pick_strategy: str
    carrier: str
    status: str
    wave_id: Optional[str]
    provisional_carton_count: Optional[int]
    final_carton_count: Optional[int]
    shipping_label_id: Optional[str]
    tracking_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Wave(TypedDict, total=False):
    id: str
    warehouse_id: str
    wave_code: str
    strategy: str
    order_ids: List[str]
    planned_unit_count: int
    picked_unit_count: int
    total_path_distance: float
    status: str
    released_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CycleCount(TypedDict, total=False):
    id: str
    warehouse_id: str
    bin_id: str
    lot_id: str
    book_qty: int
    counted_qty: Optional[int]
    variance_units: Optional[int]
    variance_value_cents: Optional[int]
    status: str
    scheduled_at: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
