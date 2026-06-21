"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this system carry the full common-field set (id, created_at,
updated_at, version) per PRD §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────────
class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    CUSTOMER = "Customer"
    TECHNICIAN = "Technician"
    INSPECTOR = "Inspector"


# ─── Status enums ─────────────────────────────────────────────────────────
class ServiceJobStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    INVOICED = "INVOICED"
    CLOSED = "CLOSED"
    WARRANTY = "WARRANTY"
    CANCELLED = "CANCELLED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class DispatchStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    CLEARED = "CLEARED"
    CANCELLED = "CANCELLED"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CallbackStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


# Field-value enums
class LicenseClass(str, Enum):
    JOURNEYMAN = "JOURNEYMAN"
    MASTER = "MASTER"


class Scope(str, Enum):
    OUTLET = "OUTLET"
    PANEL = "PANEL"
    EV_CHARGER = "EV_CHARGER"


class JobClass(str, Enum):
    SERVICE = "SERVICE"
    INSTALL = "INSTALL"


class Priority(str, Enum):
    STANDARD = "STANDARD"
    EMERGENCY = "EMERGENCY"


class PricingMode(str, Enum):
    FLAT_RATE = "FLAT_RATE"
    TIME_MATERIALS = "TIME_MATERIALS"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    PREMIER = "PREMIER"


# ─── Entity TypedDicts (all common_fields: true) ──────────────────────────
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    service_zip: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    license_class: str
    service_zone: str
    hourly_rate_cents: int
    on_call: bool
    created_at: str
    updated_at: str
    version: int


class MembershipPlan(TypedDict):
    id: str
    name: str
    tier: str
    monthly_fee_cents: int
    labor_discount_pct: float
    waives_dispatch_fee: bool
    priority_dispatch: bool
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    customer_id: str
    plan_id: str
    status: str
    started_at: str
    created_at: str
    updated_at: str
    version: int


class MaterialSku(TypedDict):
    id: str
    sku_code: str
    description: str
    unit_price_cents: int
    taxable: bool
    created_at: str
    updated_at: str
    version: int


class TruckStockItem(TypedDict):
    id: str
    technician_id: str
    sku_id: str
    quantity_on_hand: int
    reorder_threshold: int
    low_stock: bool
    created_at: str
    updated_at: str
    version: int


class ServiceJob(TypedDict):
    id: str
    customer_id: str
    scope: str
    job_class: str
    priority: str
    requires_permit: bool
    membership_id: Optional[str]
    pricing_mode: Optional[str]
    status: str
    total_due_cents: int
    warranty_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Estimate(TypedDict):
    id: str
    job_id: str
    pricing_mode: str
    flat_rate_cents: int
    estimated_labor_hours: float
    estimated_material_cents: int
    quoted_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    job_id: str
    technician_id: str
    window_start: str
    window_end: str
    eta: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Permit(TypedDict):
    id: str
    job_id: str
    jurisdiction: str
    permit_number: str
    status: str
    inspection_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialUsage(TypedDict):
    id: str
    job_id: str
    technician_id: str
    sku_id: str
    quantity: int
    line_total_cents: int
    voided: bool
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    job_id: str
    labor_subtotal_cents: int
    material_subtotal_cents: int
    dispatch_fee_cents: int
    emergency_surcharge_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class Callback(TypedDict):
    id: str
    job_id: str
    reason: str
    covered_by_warranty: bool
    status: str
    created_at: str
    updated_at: str
    version: int
