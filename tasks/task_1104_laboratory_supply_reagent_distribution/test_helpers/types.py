"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's resource descriptions. Every persisted resource
carries id/created_at/updated_at/version except ConsumptionRecord, which is
an immutable billing fact carrying only id and created_at.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class WarehouseStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    SUSPENDED = "SUSPENDED"


class ZoneClass(str, Enum):
    AMBIENT = "AMBIENT"
    REFRIGERATED_2_8 = "REFRIGERATED_2_8"
    FROZEN_MINUS_20 = "FROZEN_MINUS_20"
    ULTRACOLD_MINUS_80 = "ULTRACOLD_MINUS_80"


class RotationPolicy(str, Enum):
    FEFO = "FEFO"
    FIFO = "FIFO"


class HazardClass(str, Enum):
    NON_HAZARDOUS = "NON_HAZARDOUS"
    FLAMMABLE = "FLAMMABLE"
    CORROSIVE = "CORROSIVE"
    TOXIC = "TOXIC"
    OXIDIZER = "OXIDIZER"


class ProductStatus(str, Enum):
    LISTED = "LISTED"
    UNDER_RECALL = "UNDER_RECALL"
    DISCONTINUED = "DISCONTINUED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    RECALLED = "RECALLED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class HazmatEndorsement(str, Enum):
    NONE = "NONE"
    LIMITED = "LIMITED"
    FULL = "FULL"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class FulfillmentMode(str, Enum):
    ANY = "ANY"
    SEQUENTIAL = "SEQUENTIAL"


class ReservationStatus(str, Enum):
    HELD = "HELD"
    COMMITTED = "COMMITTED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class ShippingService(str, Enum):
    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"
    PRIORITY_OVERNIGHT = "PRIORITY_OVERNIGHT"


class CoolantType(str, Enum):
    NONE = "NONE"
    GEL_PACK = "GEL_PACK"
    DRY_ICE = "DRY_ICE"


class ShipmentStatus(str, Enum):
    CREATED = "CREATED"
    PACKED = "PACKED"
    IN_TRANSIT = "IN_TRANSIT"
    EXCURSION_HOLD = "EXCURSION_HOLD"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class ExcursionSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ExcursionStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    DESTROYED = "DESTROYED"
    RETURNED = "RETURNED"


class StandingOrderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class RecallScopeType(str, Enum):
    LOT_RANGE = "LOT_RANGE"
    PRODUCT_ALL = "PRODUCT_ALL"


class RecallSeverityClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


class RecallStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    CLOSED = "CLOSED"


class KitStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class JobStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    CATALOG_MANAGER = "CatalogManager"
    INVENTORY_CLERK = "InventoryClerk"
    QUALITY_MANAGER = "QualityManager"
    ACCOUNT_MANAGER = "AccountManager"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class Warehouse(TypedDict):
    id: str
    name: str
    region_code: str
    hazmat_certified: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class StorageZone(TypedDict):
    id: str
    warehouse_id: str
    zone_class: str
    capacity_units: int
    rotation_policy: str
    occupied_units: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    storage_requirement: str
    hazard_class: str
    unit_haz_factor: int
    max_qty_per_shipment: int
    unit_price_cents: int
    requires_cold_chain: bool
    shelf_life_days: int
    min_remaining_shelf_life_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReagentLot(TypedDict):
    id: str
    product_id: str
    warehouse_id: str
    storage_zone_id: str
    lot_sequence_number: int
    quantity_received: int
    quantity_on_hand: int
    quantity_reserved: int
    quantity_consumed: int
    adjustment_total: int
    manufacture_date: str
    expiry_date: str
    received_at: str
    recall_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict):
    id: str
    name: str
    credit_limit_cents: int
    volume_discount_pct: float
    hazmat_endorsement: str
    cold_chain_certified: bool
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict):
    id: str
    customer_id: str
    warehouse_id: str
    shipping_service: str
    requested_ship_date: str
    product_total_cents: Optional[int]
    submission_seq: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    product_id: str
    quantity: int
    fulfillment_mode: str
    unit_price_cents: Optional[int]
    line_total_cents: Optional[int]
    allocated_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LotReservation(TypedDict):
    id: str
    order_line_id: str
    lot_id: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    coolant_type: str
    coolant_units: int
    declared_weight_grams: int
    actual_weight_grams: Optional[int]
    temp_min_celsius: float
    temp_max_celsius: float
    provisional_freight_cents: int
    final_freight_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TemperatureExcursion(TypedDict):
    id: str
    shipment_id: str
    peak_temp_celsius: float
    duration_minutes: int
    deviation_degrees: float
    severity: str
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class StandingOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    warehouse_id: str
    quantity_per_run: int
    interval_days: int
    effective_from: str
    effective_until: str
    next_run_date: str
    generated_order_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsignmentAgreement(TypedDict):
    id: str
    customer_id: str
    product_id: str
    ceiling_quantity: int
    stocked_quantity: int
    consumed_quantity: int
    reorder_point: int
    contract_unit_price_cents: int
    discount_pct: float
    replenishment_warehouse_id: str
    initial_stocked_quantity: int
    effective_from: str
    effective_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsumptionRecord(TypedDict):
    # Immutable billing fact: only id + created_at; no updated_at, no version.
    id: str
    agreement_id: str
    quantity: int
    unit_price_cents: int
    charge_cents: int
    recorded_at: str
    created_at: str


class RecallNotice(TypedDict):
    id: str
    product_id: str
    scope_type: str
    scope_lot_seq_min: Optional[int]
    scope_lot_seq_max: Optional[int]
    severity_class: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class KitDefinition(TypedDict):
    id: str
    customer_id: str
    name: str
    components: List[Dict[str, Any]]
    kit_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class KitAssemblyJob(TypedDict):
    id: str
    kit_id: str
    warehouse_id: str
    quantity_to_build: int
    kits_built: int
    consumption_summary: Optional[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int
