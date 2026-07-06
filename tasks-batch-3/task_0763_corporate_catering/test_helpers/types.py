"""Domain types: entity TypedDicts, status enums, role enum.

All names use PRD terminology. Two entities (WasteEvent, SatisfactionSurvey) are
immutable append-only records carrying only id + created_at (no updated_at/version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    SITE_ADMIN = "SiteAdmin"
    CAFETERIA_MANAGER = "CafeteriaManager"
    DINER = "Diner"
    CATERING_COORDINATOR = "CateringCoordinator"
    CATERING_APPROVER = "CateringApprover"
    FINANCE_CONTROLLER = "FinanceController"


# ─── Status enums ─────────────────────────────────────────────────────────────
class ClientSiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CostStatus(str, Enum):
    ON_TARGET = "ON_TARGET"
    OVER_TARGET = "OVER_TARGET"


class EmployeeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class MenuCycleStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class MenuItemStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ServiceSessionStatus(str, Enum):
    PLANNED = "PLANNED"
    FORECAST_LOCKED = "FORECAST_LOCKED"
    IN_SERVICE = "IN_SERVICE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BadgeTransactionStatus(str, Enum):
    COMPLETED = "COMPLETED"
    VOIDED = "VOIDED"


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class InventoryLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class CateringOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    CONFIRMED = "CONFIRMED"
    FULFILLED = "FULFILLED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class VendorInvoiceStatus(str, Enum):
    RECEIVED = "RECEIVED"
    MATCHED = "MATCHED"
    APPROVED = "APPROVED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


# ─── Entity TypedDicts (common_fields: true carry id/created_at/updated_at/version) ──
class ClientSite(TypedDict, total=False):
    id: str
    name: str
    client_name: str
    currency: str
    employer_subsidy_pct: float
    daily_subsidy_cap_cents: int
    food_cost_target_pct: float
    session_changeover_buffer_minutes: int
    status: str
    cost_status: str
    period_food_cost_cents: int
    period_revenue_cents: int
    food_cost_pct: Optional[float]
    inventory_value_cents: int
    satisfaction_avg: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    client_site_id: str
    badge_id: str
    full_name: str
    restricted_allergens: List[str]
    wallet_balance_cents: int
    daily_subsidy_used_cents: int
    subsidy_day: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuCycle(TypedDict, total=False):
    id: str
    client_site_id: str
    name: str
    cycle_length_weeks: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MenuItem(TypedDict, total=False):
    id: str
    menu_cycle_id: str
    name: str
    category: str
    price_cents: int
    standard_recipe_cost_cents: int
    allergens: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CateringVenue(TypedDict, total=False):
    id: str
    client_site_id: str
    name: str
    capacity: int
    created_at: str
    updated_at: str
    version: int


class ServiceSession(TypedDict, total=False):
    id: str
    client_site_id: str
    menu_cycle_id: str
    service_date: str
    meal_period: str
    window_start: str
    window_end: str
    forecast_headcount: int
    actual_headcount: int
    revenue_cents: int
    actual_food_cost_cents: Optional[int]
    theoretical_food_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BadgeTransaction(TypedDict, total=False):
    id: str
    employee_id: str
    service_session_id: str
    lines: List[dict]
    payment_method: str
    subtotal_cents: int
    subsidy_applied_cents: int
    employee_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    name: str
    category: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    vendor_id: str
    client_site_id: str
    lines: List[dict]
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    client_site_id: str
    purchase_order_id: str
    ingredient: str
    qty_received: int
    qty_on_hand: int
    qty_reserved: int
    unit_cost_cents: int
    received_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CateringOrder(TypedDict, total=False):
    id: str
    client_site_id: str
    venue_id: str
    coordinator_id: str
    event_date: str
    event_start: str
    event_end: str
    headcount: int
    lines: List[dict]
    estimated_cost_cents: int
    final_cost_cents: Optional[int]
    order_charge_cents: int
    service_fee_cents: int
    total_charge_cents: int
    requires_finance_review: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorInvoice(TypedDict, total=False):
    id: str
    vendor_id: str
    purchase_order_id: str
    invoiced_amount_cents: int
    matched_variance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entities: id + created_at ONLY (no updated_at, no version) ──────
class WasteEvent(TypedDict, total=False):
    id: str
    client_site_id: str
    inventory_lot_id: str
    qty: int
    reason: str
    cost_cents: int
    created_at: str


class SatisfactionSurvey(TypedDict, total=False):
    id: str
    client_site_id: str
    service_session_id: Optional[str]
    catering_order_id: Optional[str]
    rating: int
    comment: str
    created_at: str
