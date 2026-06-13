"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Carpet & Upholstery Cleaning PRD entity model.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enums ──────────────────────────────────────────────

class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class RecurringPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class JobLifecycleStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class JobBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class SlotStatus(str, Enum):
    RESERVED = "RESERVED"
    RELEASED = "RELEASED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"
    VOID = "VOID"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


# ─── Enumerated input domains ──────────────────────────────────

class ServiceType(str, Enum):
    STEAM = "STEAM"
    DRY = "DRY"


class SoilingLevel(str, Enum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    HEAVY = "HEAVY"


class AddOnType(str, Enum):
    STAIN = "STAIN"
    PET = "PET"
    PROTECTANT = "PROTECTANT"


class Cadence(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMIANNUAL = "SEMIANNUAL"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    CASH = "CASH"
    CHECK = "CHECK"


class LedgerReason(str, Enum):
    GUARANTEE_CREDIT = "GUARANTEE_CREDIT"
    INVOICE_APPLIED = "INVOICE_APPLIED"
    INVOICE_REFUND = "INVOICE_REFUND"


# ─── Role enum ─────────────────────────────────────────────────

class UserRole(str, Enum):
    CUSTOMER = "Customer"
    DISPATCHER = "Dispatcher"
    SERVICE_MANAGER = "ServiceManager"
    BILLING = "Billing"


# ─── Entity TypedDicts ─────────────────────────────────────────
# Entities below carry common fields: id, created_at, updated_at, version.

class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    wallet_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCatalog(TypedDict):
    id: str
    service_type: str
    base_rate_cents_per_sqft: int
    stain_addon_cents: int
    pet_addon_cents: int
    protectant_cents_per_sqft: int
    move_furniture_flat_cents: int
    dry_time_minutes: int
    created_at: str
    updated_at: str
    version: int


class Crew(TypedDict):
    id: str
    crew_name: str
    supported_service_type: str
    turnaround_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecurringPlan(TypedDict):
    id: str
    customer_id: str
    cadence: str
    completed_visit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CleaningJob(TypedDict):
    id: str
    customer_id: str
    service_catalog_id: str
    recurring_plan_id: Optional[str]
    origin_job_id: Optional[str]
    move_furniture: bool
    total_sqft: int
    quoted_price_cents: Optional[int]
    settled_price_cents: Optional[int]
    lifecycle_status: str
    billing_status: str
    completed_at_minute: Optional[int]
    scheduled_slot_id: Optional[str]
    invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoomAssessment(TypedDict):
    id: str
    cleaning_job_id: str
    area_label: str
    area_sqft: int
    soiling_level: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    cleaning_job_id: str
    addon_type: str
    line_price_cents: int
    created_at: str
    updated_at: str
    version: int


class ScheduledSlot(TypedDict):
    id: str
    crew_id: str
    cleaning_job_id: str
    start_minute: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    cleaning_job_id: str
    amount_due_cents: int
    wallet_applied_cents: int
    net_payable_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GuaranteeClaim(TypedDict):
    id: str
    cleaning_job_id: str
    reason: str
    filed_at_minute: int
    reclean_job_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger record — carries ONLY id + created_at (no updated_at, no version).
class WalletLedgerEntry(TypedDict):
    id: str
    customer_id: str
    delta_cents: int
    reason: str
    cleaning_job_id: Optional[str]
    created_at: str
