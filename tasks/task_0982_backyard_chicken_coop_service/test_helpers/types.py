"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SERVICE_TECH = "ServiceTech"
    DISPATCHER = "Dispatcher"
    BILLING_ADMIN = "BillingAdmin"
    PLATFORM_ADMIN = "PlatformAdmin"


class ZoneCode(str, Enum):
    URBAN = "URBAN"
    SUBURBAN = "SUBURBAN"
    RURAL = "RURAL"


class HouseholdStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class CoopStatus(str, Enum):
    PLANNED = "PLANNED"
    INSTALLED = "INSTALLED"


class PredatorGrade(str, Enum):
    NONE = "NONE"
    B = "B"
    A = "A"


class VisitType(str, Enum):
    COOP_CLEANING = "COOP_CLEANING"
    FLOCK_HEALTH_CHECK = "FLOCK_HEALTH_CHECK"
    PREDATOR_PROOFING = "PREDATOR_PROOFING"
    SETUP_INSTALL = "SETUP_INSTALL"


class VisitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    RESCHEDULE_REQUESTED = "RESCHEDULE_REQUESTED"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class Coverage(str, Enum):
    SUBSCRIPTION_COVERED = "SUBSCRIPTION_COVERED"
    BILLABLE = "BILLABLE"


class EngagementStatus(str, Enum):
    REQUESTED = "REQUESTED"
    QUOTED = "QUOTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"
    SKIPPED = "SKIPPED"
    REMOVED = "REMOVED"


class ProductCategory(str, Enum):
    FEED = "FEED"
    BEDDING = "BEDDING"
    EGG_SUPPLIES = "EGG_SUPPLIES"
    HEALTH = "HEALTH"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PLACED = "PLACED"
    FULFILLED = "FULFILLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOID = "VOID"


class InvoiceLineSourceType(str, Enum):
    VISIT = "VISIT"
    SITTING = "SITTING"
    ORDER = "ORDER"
    SUBSCRIPTION_FEE = "SUBSCRIPTION_FEE"
    CANCELLATION_FEE = "CANCELLATION_FEE"
    ADJUSTMENT = "ADJUSTMENT"


# --- Primary resources: id + created_at + updated_at + version (PRD §2.4) ---

class HouseholdAccount(TypedDict, total=False):
    id: str
    name: str
    email: str
    address: str
    zone_code: str
    status: str
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    household_id: str
    plan_id: str
    pending_plan_id: Optional[str]
    status: str
    current_period_start: str
    current_period_end: str
    used_cleanings: int
    used_health_checks: int
    created_at: str
    updated_at: str
    version: int


class CoopSite(TypedDict, total=False):
    id: str
    household_id: str
    site_label: str
    coop_capacity_hens: int
    predator_grade: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict, total=False):
    id: str
    household_id: str
    coop_site_id: str
    subscription_id: Optional[str]
    visit_type: str
    scheduled_start: str
    scheduled_end: str
    coverage: str
    provisional_price_cents: int
    final_price_cents: Optional[int]
    assigned_technician_id: Optional[str]
    reschedule_count: int
    status: str
    billed_invoice_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SittingEngagement(TypedDict, total=False):
    id: str
    household_id: str
    coop_site_id: str
    start_date: str
    end_date: str
    daily_window_start: str
    status: str
    quoted_price_cents: Optional[int]
    final_price_cents: Optional[int]
    cancellation_fee_cents: int
    cancelled_at: Optional[str]
    settled_at: Optional[str]
    billed_invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SittingRoute(TypedDict, total=False):
    id: str
    technician_id: str
    route_date: str
    zone_code: str
    max_stops: int
    committed_stops: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    id: str
    route_id: str
    engagement_id: str
    planned_start: str
    planned_end: str
    sequence: int
    status: str
    skip_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    product_sku: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class SupplyOrder(TypedDict, total=False):
    id: str
    household_id: str
    fulfillment_visit_id: Optional[str]
    status: str
    lines: List[OrderLine]
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    placed_at: Optional[str]
    billed_invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    household_id: str
    period_start: str
    period_end: str
    status: str
    subtotal_cents: int
    tax_cents: int
    total_cents: int
    credit_applied_cents: int
    amount_due_cents: int
    due_date: Optional[str]
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Immutable config / subordinate resources: ONLY id + created_at (PRD §2.4) ---

class SubscriptionPlan(TypedDict, total=False):
    id: str
    plan_code: str
    monthly_fee_cents: int
    included_cleanings_per_period: int
    included_health_checks_per_period: int
    supply_discount_pct: float
    sitting_discount_pct: float
    created_at: str


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    category: str
    unit_price_cents: int
    active: bool
    created_at: str


class InvoiceLine(TypedDict, total=False):
    id: str
    invoice_id: str
    source_type: str
    source_id: str
    description: str
    amount_cents: int
    created_at: str


class SeasonalWindow(TypedDict, total=False):
    id: str
    window_code: str
    zone_code: str
    start_md: str
    end_md: str
    visit_surcharge_pct: float
    sitting_surcharge_pct: float
    created_at: str
