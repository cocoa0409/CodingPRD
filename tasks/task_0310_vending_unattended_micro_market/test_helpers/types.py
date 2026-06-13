"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Vending Micro-Market Operations API PRD (Sections 2-3).
A Sale is an immutable event record carrying only id + created_at — it has
neither updated_at nor version. Every other entity carries the full common-field
set (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────────

class HostSiteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CommissionModel(str, Enum):
    FLAT = "FLAT"
    TIERED = "TIERED"


class ProductCategory(str, Enum):
    BEVERAGE = "BEVERAGE"
    SNACK = "SNACK"
    FRESH_FOOD = "FRESH_FOOD"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class MachineType(str, Enum):
    SNACK_VENDOR = "SNACK_VENDOR"
    BEVERAGE_VENDOR = "BEVERAGE_VENDOR"
    MICRO_MARKET_KIOSK = "MICRO_MARKET_KIOSK"


class StockStatus(str, Enum):
    STOCKED = "STOCKED"
    LOW_STOCK = "LOW_STOCK"
    STOCKOUT = "STOCKOUT"


class CashStatus(str, Enum):
    CASH_OK = "CASH_OK"
    CASH_FULL_WARN = "CASH_FULL_WARN"


class ServiceStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    FROZEN = "FROZEN"


class SlotStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    SPOILED = "SPOILED"


class RouteStatus(str, Enum):
    DRAFT = "DRAFT"
    DISPATCHED = "DISPATCHED"
    CLOSED = "CLOSED"


class DriverStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class RouteStopStatus(str, Enum):
    PLANNED = "PLANNED"
    KITTED = "KITTED"
    VISITED = "VISITED"
    SKIPPED = "SKIPPED"


class VisitStatus(str, Enum):
    DRAFT = "DRAFT"
    RECONCILED = "RECONCILED"
    REJECTED = "REJECTED"


class PaymentMethod(str, Enum):
    CASHLESS = "CASHLESS"
    CASH = "CASH"


class SettlementStatus(str, Enum):
    SETTLED = "SETTLED"
    VOID = "VOID"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class IssueType(str, Enum):
    JAM = "JAM"
    TELEMETRY_ALERT = "TELEMETRY_ALERT"
    VANDALISM = "VANDALISM"
    COIN_MECH = "COIN_MECH"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    REOPENED = "REOPENED"


class UserRole(str, Enum):
    FIELD_OPS = "FieldOps"
    ROUTE_DRIVER = "RouteDriver"
    HOST_MANAGER = "HostManager"
    FINANCE_CLERK = "FinanceClerk"


# ─── Entity TypedDicts (common_fields: true) ──────────────────────────────

class HostSite(TypedDict):
    id: str
    name: str
    contact_email: str
    commission_model: str
    flat_commission_pct: float
    monthly_guarantee_cents: int
    lifetime_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    unit_cost_cents: int
    shelf_life_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Machine(TypedDict):
    id: str
    host_site_id: str
    asset_tag: str
    machine_type: str
    cash_capacity_cents: int
    cash_on_hand_cents: int
    cash_alert_threshold_pct: float
    par_fill_threshold_pct: float
    stock_status: str
    cash_status: str
    service_status: str
    created_at: str
    updated_at: str
    version: int


class PlanogramSlot(TypedDict):
    id: str
    machine_id: str
    product_id: str
    slot_code: str
    capacity: int
    par_level: int
    price_cents: int
    on_hand: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    slot_id: str
    machine_id: str
    filled_units: int
    unit_cost_cents: int
    remaining_units: int
    expiration_date: Optional[str]
    restock_visit_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteDriverProfile(TypedDict):
    id: str
    full_name: str
    employee_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RestockRoute(TypedDict):
    id: str
    driver_id: str
    service_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict):
    id: str
    route_id: str
    machine_id: str
    window_start_min: int
    window_end_min: int
    prekit_json: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class RestockVisit(TypedDict):
    id: str
    route_stop_id: str
    machine_id: str
    counted_lines: list
    total_shrink_units: int
    shrink_value_cents: int
    expected_machine_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CommissionStatement(TypedDict):
    id: str
    host_site_id: str
    period_start: str
    period_end: str
    gross_sales_cents: int
    shrink_chargeback_cents: int
    gross_commission_cents: int
    net_commission_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceTicket(TypedDict):
    id: str
    machine_id: str
    issue_type: str
    blocking: bool
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Immutable event entity (common_fields: false) ────────────────────────
# A Sale carries ONLY id + created_at — no updated_at, no version.

class Sale(TypedDict):
    id: str
    machine_id: str
    slot_id: str
    lot_consumption_json: list
    quantity: int
    unit_price_cents: int
    gross_cents: int
    provisional_cogs_cents: int
    payment_method: str
    settlement_status: str
    created_at: str
