"""Domain types: entity TypedDicts, status enums, role enum for the 3PL fulfillment API."""
from enum import Enum
from typing import TypedDict, Optional, List


# --- Status enums ---

class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SkuStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class BinType(str, Enum):
    GENERAL = "GENERAL"
    PALLET = "PALLET"


class BinStatus(str, Enum):
    OPEN = "OPEN"
    BLOCKED = "BLOCKED"


class ReceiptStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    RECEIVED = "RECEIVED"
    PUTAWAY = "PUTAWAY"
    CANCELLED = "CANCELLED"


class OrderStatus(str, Enum):
    IMPORTED = "IMPORTED"
    RESERVED = "RESERVED"
    PICKING = "PICKING"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"
    SHORT = "SHORT"


class WaveStatus(str, Enum):
    BUILDING = "BUILDING"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PickTaskStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    PICKED = "PICKED"
    SHORT_CLOSED = "SHORT_CLOSED"


class CartonSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class CartonStatus(str, Enum):
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    VOIDED = "VOIDED"


class Carrier(str, Enum):
    GROUND_ECONOMY = "GROUND_ECONOMY"
    GROUND_PLUS = "GROUND_PLUS"
    AIR_EXPRESS = "AIR_EXPRESS"


class ShipmentStatus(str, Enum):
    LABELLED = "LABELLED"
    DELIVERED = "DELIVERED"
    VOIDED = "VOIDED"


class ReturnGrade(str, Enum):
    SELLABLE = "SELLABLE"
    DAMAGED = "DAMAGED"


class ReturnStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRADED = "GRADED"
    CLOSED = "CLOSED"


class CycleCountStatus(str, Enum):
    APPLIED = "APPLIED"


class ChargeType(str, Enum):
    STORAGE = "STORAGE"
    HANDLING = "HANDLING"


class UserRole(str, Enum):
    BILLING_CLERK = "BillingClerk"
    CLIENT_USER = "ClientUser"
    RECEIVING_CLERK = "ReceivingClerk"
    WAVE_PLANNER = "WavePlanner"
    PICK_OPERATOR = "PickOperator"
    PACK_STATION = "PackStation"
    SHIP_STATION = "ShipStation"
    RETURNS_CLERK = "ReturnsClerk"


# --- Entity TypedDicts ---
# All standard entities carry id, created_at, updated_at, version.
# BillingCharge is append-only: only id + created_at (no updated_at, no version).

class Client(TypedDict):
    id: str
    name: str
    storage_rate_per_pallet_cents: int
    handling_rate_per_order_cents: int
    handling_rate_per_extra_unit_cents: int
    handling_surcharge_per_extra_carton_cents: int
    carrier_discount_bps: int
    storage_balance_cents: int
    handling_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Sku(TypedDict):
    id: str
    client_id: str
    code: str
    unit_volume_cc: int
    unit_cost_cents: int
    hazmat: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Bin(TypedDict):
    id: str
    location_code: str
    bin_type: str
    capacity_cc: int
    occupied_cc: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    client_id: str
    sku_id: str
    bin_id: str
    receipt_id: str
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class Receipt(TypedDict):
    id: str
    client_id: str
    sku_id: str
    bin_id: str
    expected_qty: int
    received_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    client_id: str
    wave_id: Optional[str]
    ship_to_zone: int
    lines: List[dict]
    total_units: int
    estimated_handling_cents: int
    billed_handling_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Wave(TypedDict):
    id: str
    client_id: str
    order_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PickTask(TypedDict):
    id: str
    order_id: str
    lot_id: str
    sku_id: str
    qty: int
    picked_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Carton(TypedDict):
    id: str
    order_id: str
    packed_units: int
    fill_volume_cc: int
    carton_size: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    carrier: str
    quoted_cost_cents: int
    tracking_number: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict):
    id: str
    order_id: str
    sku_id: str
    bin_id: str
    qty: int
    grade: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CycleCount(TypedDict):
    id: str
    lot_id: str
    expected_lot_version: int
    counted_qty: int
    variance_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger event: ONLY id + created_at (no updated_at, no version).
class BillingCharge(TypedDict):
    id: str
    client_id: str
    charge_type: str
    amount_cents: int
    source_order_id: Optional[str]
    posted: bool
    created_at: str
