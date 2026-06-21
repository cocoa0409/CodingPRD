"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity model and lifecycle definitions. Monetary fields are
integer cents; truck_stock_markup_pct, estimated_labor_hours, hours_worked, and
callback_rate are the only non-monetary numerics.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────

class JobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    INSTANT_QUOTED = "INSTANT_QUOTED"
    ESTIMATE_REQUESTED = "ESTIMATE_REQUESTED"
    ESTIMATED = "ESTIMATED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CALLBACK_OPEN = "CALLBACK_OPEN"
    CANCELLED = "CANCELLED"


class QuotePath(str, Enum):
    INSTANT = "INSTANT"
    IN_HOME = "IN_HOME"


class QuoteType(str, Enum):
    INSTANT = "INSTANT"
    IN_HOME = "IN_HOME"


class PricingModel(str, Enum):
    HOURLY = "HOURLY"
    FLAT = "FLAT"


class HoldState(str, Enum):
    FREE = "FREE"
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DisputeReason(str, Enum):
    WORK_INCOMPLETE = "WORK_INCOMPLETE"
    OVERCHARGED = "OVERCHARGED"
    DAMAGE = "DAMAGE"
    NO_SHOW = "NO_SHOW"


class RefundDestination(str, Enum):
    ORIGINAL = "ORIGINAL"
    WALLET = "WALLET"


class BackgroundCheckType(str, Enum):
    CRIMINAL = "CRIMINAL"
    IDENTITY = "IDENTITY"
    LICENSE = "LICENSE"


class BackgroundCheckDecision(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class BackgroundCheckStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FLAGGED = "FLAGGED"


class LicenseStatus(str, Enum):
    NONE = "NONE"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"


class WorkVisitOutcome(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    PRO = "Pro"
    PLATFORM_ADMIN = "PlatformAdmin"
    DISPATCHER = "Dispatcher"
    ANONYMOUS = "Anonymous"


# ─── Entity TypedDicts ────────────────────────────────────────

# ServiceCategory is immutable configuration data: it carries ONLY id and
# created_at — no updated_at, no version.
class ServiceCategory(TypedDict, total=False):
    id: str
    created_at: str
    code: str
    name: str
    requires_license: bool
    pricing_model: str
    flat_task_fee_cents: Optional[int]
    hourly_rate_cents: Optional[int]
    instant_quote_eligible: bool
    instant_quote_flat_cents: Optional[int]
    callback_warranty_days: int
    skill_tags: List[str]


class Customer(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    full_name: str
    zip_code: str
    wallet_credit_cents: int


class Pro(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    full_name: str
    home_zip_code: str
    skill_tags: List[str]
    background_check_status: str
    license_status: str
    license_expires_on: Optional[str]
    truck_stock_markup_pct: float
    completed_job_count: int
    callback_job_count: int
    callback_rate: float


class Job(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    customer_id: str
    category_id: str
    pro_id: Optional[str]
    parent_job_id: Optional[str]
    status: str
    quote_path: Optional[str]
    agreed_price_cents: Optional[int]
    is_warranty_callback: bool
    address_zip_code: str


class Quote(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    quote_type: str
    estimated_labor_hours: Optional[float]
    priced_amount_cents: int
    accepted: bool
    superseded: bool


class DispatchWindow(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    pro_id: str
    window_start: str
    window_end: str
    service_zip_code: str
    booked_job_id: Optional[str]
    hold_state: str


class LaborLine(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    hours_worked: float
    rate_cents_per_hour: int
    line_total_cents: int


class PartLine(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    description: str
    unit_cost_cents: int
    quantity: int
    from_truck_stock: bool
    line_total_cents: int


class WorkVisit(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    dispatch_window_id: str
    arrived_at: str
    outcome: str


class Invoice(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    labor_subtotal_cents: int
    parts_subtotal_cents: int
    trip_fee_cents: int
    total_cents: int
    amount_paid_cents: int
    refunded_cents: int
    balance_due_cents: int
    status: str


class Dispute(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    job_id: str
    invoice_id: str
    reason: str
    requested_refund_cents: int
    refund_destination: str
    approved_refund_cents: Optional[int]
    status: str


class BackgroundCheck(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    pro_id: str
    check_type: str
    license_expires_on: Optional[str]
    decision: str
