"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource model. Every persisted resource carries the
common fields id, created_at, updated_at, and version (PRD Section 2.4).
"""
from enum import Enum
from typing import TypedDict, List


class UserRole(str, Enum):
    OPERATIONS_MANAGER = "OperationsManager"
    ORGANIZER = "Organizer"
    BILLING_ADMIN = "BillingAdmin"
    CLIENT = "Client"


class BillingMode(str, Enum):
    HOURLY = "HOURLY"
    PROJECT = "PROJECT"


class ProjectStatus(str, Enum):
    SCOPING = "SCOPING"
    ACTIVE = "ACTIVE"
    WRAP_UP = "WRAP_UP"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Disposition(str, Enum):
    KEEP = "KEEP"
    HAUL = "HAUL"
    DONATE = "DONATE"
    SELL = "SELL"


class InventoryItemStatus(str, Enum):
    LOGGED = "LOGGED"
    SCHEDULED_HAUL = "SCHEDULED_HAUL"
    SCHEDULED_DONATION = "SCHEDULED_DONATION"
    HAULED = "HAULED"
    DONATED = "DONATED"
    KEPT = "KEPT"


class ProductCategory(str, Enum):
    BIN = "BIN"
    SHELVING = "SHELVING"
    SYSTEM = "SYSTEM"
    LABELING = "LABELING"


class ProductLineStatus(str, Enum):
    QUOTED = "QUOTED"
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class Cadence(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    BIANNUAL = "BIANNUAL"


class MaintenancePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


# --- Entity TypedDicts (all resources carry id/created_at/updated_at/version) ---

class Client(TypedDict):
    id: str
    full_name: str
    email: str
    home_address: str
    access_notes: str
    created_at: str
    updated_at: str
    version: int


class Organizer(TypedDict):
    id: str
    full_name: str
    email: str
    hourly_rate_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict):
    id: str
    client_id: str
    lead_organizer_id: str
    title: str
    billing_mode: str
    flat_price_cents: int
    scope_rooms: List[str]
    move_addon_requested: bool
    move_box_count: int
    status: str
    accrued_labor_hours: float
    projected_product_cost_cents: int
    projected_haul_cost_cents: int
    donation_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    project_id: str
    organizer_id: str
    scheduled_start: str
    scheduled_end: str
    logged_hours: float
    labor_cost_cents: int
    is_overtime: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    project_id: str
    room_label: str
    description: str
    disposition: str
    estimated_value_cents: int
    final_value_cents: int
    haul_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductLine(TypedDict):
    id: str
    project_id: str
    product_name: str
    category: str
    wholesale_cost_cents: int
    quantity: int
    markup_pct: float
    client_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    project_id: str
    expected_project_version: int
    billing_mode: str
    labor_subtotal_cents: int
    product_subtotal_cents: int
    haul_subtotal_cents: int
    donation_credit_cents: int
    move_addon_cents: int
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    grand_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenancePlan(TypedDict):
    id: str
    project_id: str
    cadence: str
    monthly_fee_cents: int
    visits_per_year: int
    next_followup_note: str
    status: str
    created_at: str
    updated_at: str
    version: int
