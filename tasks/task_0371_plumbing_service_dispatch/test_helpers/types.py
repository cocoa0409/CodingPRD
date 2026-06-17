"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Plumbing Service Dispatch PRD. Entities that are immutable
after creation (MembershipPlan, FlatRateItem, Part per PRD §2.4) carry only
`id` and `created_at` and therefore omit `updated_at` / `version`. All other
entities carry the full common-field set.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum (PRD §2.1) ─────────────────────────────────────────────
class UserRole(str, Enum):
    OFFICE_MANAGER = "OfficeManager"
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    CUSTOMER = "Customer"


# ─── Status enums ─────────────────────────────────────────────────────
class TechnicianStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_CALL = "ON_CALL"
    OFF_DUTY = "OFF_DUTY"


class ServiceJobStatus(str, Enum):
    RECEIVED = "RECEIVED"
    DISPATCHED = "DISPATCHED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    AUTHORIZED = "AUTHORIZED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    REOPENED = "REOPENED"
    CANCELLED = "CANCELLED"


class DispatchAssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    EN_ROUTE = "EN_ROUTE"
    ON_SITE = "ON_SITE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EstimateStatus(str, Enum):
    DRAFT = "DRAFT"
    PRESENTED = "PRESENTED"
    REVISED = "REVISED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    CONSUMED = "CONSUMED"


class LineType(str, Enum):
    FLAT_RATE = "FLAT_RATE"
    PART = "PART"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    ISSUED = "ISSUED"
    INSPECTION_SCHEDULED = "INSPECTION_SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class InspectionResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class InvoiceStatus(str, Enum):
    FINALIZED = "FINALIZED"
    VOIDED = "VOIDED"


class CallbackStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    RESOLVED = "RESOLVED"


class TierCode(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ServiceCategory(str, Enum):
    LEAK = "LEAK"
    DRAIN = "DRAIN"
    WATER_HEATER = "WATER_HEATER"
    REPIPE = "REPIPE"
    GENERAL = "GENERAL"


class JobPriority(str, Enum):
    STANDARD = "STANDARD"
    EMERGENCY = "EMERGENCY"


# ─── Entity TypedDicts ────────────────────────────────────────────────
# Immutable config resources (PRD §2.4): id + created_at only.

class MembershipPlan(TypedDict):
    id: str
    created_at: str
    tier_code: str
    name: str
    labor_discount_pct: float
    waives_trip_fee: bool
    annual_fee_cents: int


class FlatRateItem(TypedDict):
    id: str
    created_at: str
    code: str
    category: str
    base_price_cents: int
    skill_required: int
    requires_permit: bool


class Part(TypedDict):
    id: str
    created_at: str
    sku: str
    name: str
    list_price_cents: int


# Versioned resources: full common-field set.

class Customer(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    service_address: str
    membership_plan_id: Optional[str]
    credit_limit_cents: int
    committed_credit_cents: int


class Technician(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    skill_level: int
    licensed_for_permits: bool
    status: str
    lifetime_completed_count: int
    lifetime_callback_count: int
    needs_restock_skus: int


class Inspector(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    name: str
    jurisdiction: str
    max_daily_inspections: int


class TruckStock(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    technician_id: str
    part_id: str
    quantity: int
    reorder_point: int
    needs_restock: bool


class ServiceJob(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    category: str
    priority: str
    window_start: Optional[str]
    after_hours: bool
    status: str
    authorized_estimate_id: Optional[str]
    authorized_amount_cents: int
    completed_at: Optional[str]


class DispatchAssignment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    technician_id: str
    window_start: str
    window_end: str
    eta: str
    status: str


class Estimate(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    status: str
    labor_subtotal_cents: int
    parts_subtotal_cents: int
    discount_cents: int
    trip_fee_cents: int
    emergency_surcharge_cents: int
    estimate_total_cents: int


class EstimateLine(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    estimate_id: str
    line_type: str
    flat_rate_item_id: Optional[str]
    part_id: Optional[str]
    quantity: int
    unit_price_cents: int
    line_total_cents: int


class Permit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    jurisdiction: str
    status: str
    reapply_count: int


class InspectionVisit(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    permit_id: str
    inspector_id: str
    scheduled_date: str
    result: str


class Invoice(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    status: str
    final_labor_cents: int
    final_parts_cents: int
    final_total_cents: int


class Callback(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    original_job_id: str
    reason: str
    status: str
    within_warranty: bool
