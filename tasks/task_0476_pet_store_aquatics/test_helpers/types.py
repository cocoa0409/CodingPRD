"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    INVENTORY_MANAGER = "InventoryManager"
    LIVESTOCK_KEEPER = "LivestockKeeper"
    CLINIC_VET = "ClinicVet"
    STORE_CLERK = "StoreClerk"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class StoreStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ProductCategory(str, Enum):
    FOOD = "FOOD"
    HABITAT = "HABITAT"
    ACCESSORY = "ACCESSORY"
    MEDICATION = "MEDICATION"


class ProductRecallState(str, Enum):
    CLEAR = "CLEAR"
    RECALLED = "RECALLED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DEPLETED = "DEPLETED"


class AnimalClass(str, Enum):
    FISH = "FISH"
    REPTILE = "REPTILE"
    SMALL_ANIMAL = "SMALL_ANIMAL"


class BatchHealthState(str, Enum):
    QUARANTINE = "QUARANTINE"
    HEALTHY = "HEALTHY"
    UNDER_TREATMENT = "UNDER_TREATMENT"
    CONDEMNED = "CONDEMNED"


class BatchSaleState(str, Enum):
    HELD = "HELD"
    ON_FLOOR = "ON_FLOOR"
    RESERVED = "RESERVED"
    SOLD_OUT = "SOLD_OUT"


class LoyaltyTier(str, Enum):
    BRONZE = "BRONZE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class PrescriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ServiceType(str, Enum):
    GROOMING = "GROOMING"
    VACCINE = "VACCINE"
    VET_EXAM = "VET_EXAM"


class AppointmentStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    HALTED = "HALTED"
    CANCELLED = "CANCELLED"


class ShipmentStatus(str, Enum):
    FULFILLED = "FULFILLED"


class SpecialOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class RecallSeverity(str, Enum):
    ADVISORY = "ADVISORY"
    MANDATORY = "MANDATORY"


class RecallStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class AdoptionEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AdoptionPlacementStatus(str, Enum):
    PLACED = "PLACED"
    RETURNED = "RETURNED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — all entities carry common_fields: true
# (id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class Store(TypedDict):
    id: str
    name: str
    state_code: str
    loyalty_point_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    is_prescription_diet: bool
    loyalty_points_per_unit: int
    recall_state: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    store_id: str
    product_id: str
    lot_code: str
    quantity_on_hand: int
    quantity_reserved: int
    received_at: str
    expiry_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LivestockBatch(TypedDict):
    id: str
    store_id: str
    species: str
    animal_class: str
    head_count: int
    unit_price_cents: int
    intake_at: str
    quarantine_days: int
    mortality_count: int
    health_state: str
    sale_state: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    email: str
    full_name: str
    home_store_id: str
    loyalty_points: int
    lifetime_spend_cents: int
    loyalty_tier: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict):
    id: str
    customer_id: str
    product_id: str
    issued_by_appointment_id: str
    max_units_per_order: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ClinicAppointment(TypedDict):
    id: str
    store_id: str
    customer_id: str
    service_type: str
    room: str
    start_at: str
    end_at: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    customer_id: str
    product_id: str
    store_id: str
    quantity_per_cycle: int
    cycle_days: int
    discount_pct: float
    next_ship_at: str
    shipments_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    subscription_id: str
    lot_id: str
    units: int
    gross_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SpecialOrder(TypedDict):
    id: str
    customer_id: str
    product_id: str
    store_id: str
    quantity: int
    deposit_pct: float
    deposit_cents: int
    balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Recall(TypedDict):
    id: str
    product_id: str
    lot_code: Optional[str]
    severity: str
    scope_state_code: Optional[str]
    affected_lot_count: int
    halted_subscription_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdoptionEvent(TypedDict):
    id: str
    store_id: str
    partner_name: str
    event_date: str
    capacity: int
    placed_head: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdoptionPlacement(TypedDict):
    id: str
    event_id: str
    batch_id: str
    head: int
    status: str
    created_at: str
    updated_at: str
    version: int
