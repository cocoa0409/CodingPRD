"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the entities and lifecycle states described in the Warehouse Management
PRD (Sections 2-3). ReceiptEvent is append-only: it carries only id + created_at
(PRD 2.4), so its TypedDict omits updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD 2.1) ──────────────────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RECEIVING_CLERK = "ReceivingClerk"
    PUTAWAY_OPERATOR = "PutawayOperator"
    PICKER = "Picker"
    WAVE_PLANNER = "WavePlanner"
    INVENTORY_CONTROLLER = "InventoryController"


# ─── Status enums ─────────────────────────────────────────────────────────────
class AbcClass(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class LocationZone(str, Enum):
    RECEIVING = "RECEIVING"
    RESERVE = "RESERVE"
    PICK_FACE = "PICK_FACE"
    CROSS_DOCK = "CROSS_DOCK"
    STAGING = "STAGING"


class LocationStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BLOCKED = "BLOCKED"


class LpnDisposition(str, Enum):
    PUTAWAY_PENDING = "PUTAWAY_PENDING"
    STORED = "STORED"
    ALLOCATED = "ALLOCATED"
    PICKED_STAGED = "PICKED_STAGED"
    SHIPPED = "SHIPPED"
    DEPLETED = "DEPLETED"


class HandlingMode(str, Enum):
    PUTAWAY = "PUTAWAY"
    CROSS_DOCK = "CROSS_DOCK"


class AsnStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    RECEIVING = "RECEIVING"
    PUT_AWAY = "PUT_AWAY"
    CROSS_DOCKED = "CROSS_DOCKED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class AsnLineStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"
    OVER = "OVER"


class PutawayTaskStatus(str, Enum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OutboundOrderStatus(str, Enum):
    OPEN = "OPEN"
    WAVED = "WAVED"
    PICKING = "PICKING"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class AllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class WaveReleaseStatus(str, Enum):
    PLANNING = "PLANNING"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"


class WaveFulfillmentStatus(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    ALLOCATED = "ALLOCATED"
    PICKING = "PICKING"
    PICKED = "PICKED"


class PickTaskStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PICKED = "PICKED"
    SHORT = "SHORT"
    CANCELLED = "CANCELLED"


class CycleCountStatus(str, Enum):
    OPEN = "OPEN"
    COUNTED = "COUNTED"
    RECONCILED = "RECONCILED"
    REJECTED = "REJECTED"


class ReplenishmentTaskStatus(str, Enum):
    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────────
# common_fields: true entities carry id + created_at + updated_at + version.
class Sku(TypedDict):
    id: str
    sku_code: str
    description: str
    abc_class: str
    each_volume_cm3: float
    min_qty: int
    max_qty: int
    on_hand_qty: int
    available_qty: int
    cycle_count_due: bool
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    location_code: str
    zone: str
    max_volume_cm3: float
    used_volume_cm3: float
    status: str
    pick_face_for_sku_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicensePlate(TypedDict):
    id: str
    lpn_code: str
    sku_id: str
    location_id: Optional[str]
    source_asn_id: Optional[str]
    qty: int
    disposition: str
    created_at: str
    updated_at: str
    version: int


class InboundAsn(TypedDict):
    id: str
    asn_number: str
    supplier_name: str
    handling_mode: str
    status: str
    received_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AsnLine(TypedDict):
    id: str
    asn_id: str
    sku_id: str
    expected_qty: int
    received_qty: int
    line_status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only receipt record (PRD 2.4): id + created_at only.
class ReceiptEvent(TypedDict):
    id: str
    asn_id: str
    asn_line_id: str
    lpn_id: str
    received_qty: int
    created_at: str


class PutawayTask(TypedDict):
    id: str
    lpn_id: str
    target_location_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OutboundOrder(TypedDict):
    id: str
    order_number: str
    priority: int
    wave_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    sku_id: str
    ordered_qty: int
    allocated_qty: int
    picked_qty: int
    created_at: str
    updated_at: str
    version: int


class InventoryAllocation(TypedDict):
    id: str
    order_line_id: str
    lpn_id: str
    allocated_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Wave(TypedDict):
    id: str
    wave_label: str
    release_status: str
    fulfillment_status: str
    created_at: str
    updated_at: str
    version: int


class PickTask(TypedDict):
    id: str
    wave_id: str
    allocation_id: str
    light_confirmed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class CycleCount(TypedDict):
    id: str
    location_id: str
    sku_id: str
    system_qty: int
    counted_qty: Optional[int]
    variance_qty: int
    counted_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplenishmentTask(TypedDict):
    id: str
    sku_id: str
    pick_face_location_id: Optional[str]
    source_lpn_id: Optional[str]
    replen_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int
