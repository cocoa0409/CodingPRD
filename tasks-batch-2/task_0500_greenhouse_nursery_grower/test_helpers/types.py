"""Domain types: entity TypedDicts, status enums, role enum.

All names follow the Greenhouse Nursery Grower PRD vocabulary.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    GROWER_MANAGER = "GrowerManager"
    PRODUCTION_TECH = "ProductionTech"
    SALES_COORDINATOR = "SalesCoordinator"
    BROKER = "Broker"


# ─── Status enums ─────────────────────────────────────
class VarietyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ZoneStatus(str, Enum):
    OPEN_FOR_USE = "OPEN_FOR_USE"
    QUARANTINED = "QUARANTINED"
    DECOMMISSIONED = "DECOMMISSIONED"


class ZoneFillState(str, Enum):
    OPEN = "OPEN"
    TIGHT = "TIGHT"
    FULL = "FULL"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    GROWING = "GROWING"
    GRADING = "GRADING"
    SALEABLE = "SALEABLE"
    HELD = "HELD"
    CULLED = "CULLED"
    VOIDED = "VOIDED"


class InputLogEventType(str, Enum):
    CLIMATE = "CLIMATE"
    IRRIGATION = "IRRIGATION"
    FERTILIZER = "FERTILIZER"
    SCOUTING = "SCOUTING"
    GRADE = "GRADE"


class BrokerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"


class AvailabilityStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    FULFILLING = "FULFILLING"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    SHIPPED = "SHIPPED"
    RELEASED = "RELEASED"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    VOIDED = "VOIDED"


class PhytoStatus(str, Enum):
    VALID = "VALID"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


PROPAGATION_FORMS = ["PLUG", "LINER", "BARE_ROOT"]
CLIMATE_CLASSES = ["WARM", "COOL", "MIXED"]


# ─── Entity TypedDicts (common_fields: true → id+created_at+updated_at+version) ──
class CropVariety(TypedDict, total=False):
    id: str
    common_name: str
    cultivar_code: str
    propagation_form: str
    grow_cycle_days: int
    container_footprint_units: int
    ship_ready_grade_min_height_cm: float
    ship_ready_min_live_pct: float
    requires_phyto: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Zone(TypedDict, total=False):
    id: str
    name: str
    climate_class: str
    capacity_units: int
    occupied_units: int
    reserved_units: int
    free_units: int
    fill_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PropagationBatch(TypedDict, total=False):
    id: str
    variety_id: str
    zone_id: str
    lot_code: str
    source_supplier: str
    sourced_count: int
    started_count: int
    cull_count: int
    live_count: int
    shipped_count: int
    saleable_count: int
    mean_height_cm: float
    stick_date: str
    target_ship_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only event, ONLY id + created_at (no updated_at/version)
class InputLog(TypedDict, total=False):
    id: str
    batch_id: str
    event_type: str
    recorded_at: str
    temperature_c: Optional[float]
    irrigation_liters: Optional[float]
    fertilizer_ppm_n: Optional[float]
    mean_height_cm: Optional[float]
    dead_observed: int
    note: Optional[str]
    created_at: str


class Broker(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    ship_to_state: str
    credit_limit_cents: int
    open_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AvailabilityEntry(TypedDict, total=False):
    id: str
    batch_id: str
    variety_id: str
    unit_price_cents: int
    published_quantity: int
    committed_quantity: int
    available_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BrokerOrder(TypedDict, total=False):
    id: str
    broker_id: str
    requested_ship_date: str
    order_subtotal_cents: int
    freight_cents: int
    order_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    availability_entry_id: str
    quantity: int
    unit_price_cents: int
    extended_cents: int
    shipped_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    phyto_certificate_id: Optional[str]
    ship_units: int
    shipped_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PhytoCertificate(TypedDict, total=False):
    id: str
    broker_id: str
    certificate_number: str
    origin_state: str
    destination_state: str
    inspected_at: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int
