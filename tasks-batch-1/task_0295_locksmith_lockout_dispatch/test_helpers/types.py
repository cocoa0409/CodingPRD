"""Domain types: entity TypedDicts, status enums, role enum (Locksmith & Lockout Dispatch)."""
from enum import Enum
from typing import TypedDict, List


# ─── Role enum (§2.1) ─────────────────────────────────────────────────────────
class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    TECHNICIAN = "Technician"
    CUSTOMER = "Customer"
    INVENTORY_MANAGER = "InventoryManager"
    BILLING_AGENT = "BillingAgent"


# ─── Status enums ─────────────────────────────────────────────────────────────
class JobStatus(str, Enum):
    INTAKE = "INTAKE"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    WORK_COMPLETE = "WORK_COMPLETE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    REFUNDED = "REFUNDED"


class ServiceType(str, Enum):
    LOCKOUT = "LOCKOUT"
    REKEY = "REKEY"
    INSTALL = "INSTALL"
    SAFE = "SAFE"


class TechnicianStatus(str, Enum):
    ON_DUTY = "ON_DUTY"
    OFF_DUTY = "OFF_DUTY"


class JobBayStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_FOR_MAINT = "CLOSED_FOR_MAINT"


class DispatchStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    EN_ROUTE = "EN_ROUTE"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class BayBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class QuoteStatus(str, Enum):
    DRAFTED = "DRAFTED"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class LockPartStatus(str, Enum):
    STOCKED = "STOCKED"
    DISCONTINUED = "DISCONTINUED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


class AuthKind(str, Enum):
    KEY_DUPLICATION = "KEY_DUPLICATION"
    CODE_RESET = "CODE_RESET"
    RESTRICTED_BLANK = "RESTRICTED_BLANK"


class PaymentRecordStatus(str, Enum):
    CAPTURED = "CAPTURED"
    REFUNDED = "REFUNDED"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# ─── Entity TypedDicts ────────────────────────────────────────────────────────
# Mutable resources carry id + created_at + updated_at + version.
class ServiceJob(TypedDict):
    id: str
    customer_name: str
    customer_user_id: str
    service_type: str
    service_address: str
    is_emergency: bool
    requested_at_minute: int
    job_status: str
    payment_status: str
    amount_due_cents: int
    net_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    certified_for: List[str]
    status: str
    base_travel_minutes: int
    created_at: str
    updated_at: str
    version: int


class JobBay(TypedDict):
    id: str
    bay_name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispatch(TypedDict):
    id: str
    service_job_id: str
    technician_id: str
    eta_start_minute: int
    eta_end_minute: int
    promised_eta_minutes: int
    actual_response_minutes: int
    arrived_at_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BayBooking(TypedDict):
    id: str
    service_job_id: str
    job_bay_id: str
    slot_start_minute: int
    slot_end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OnSiteQuote(TypedDict):
    id: str
    service_job_id: str
    labor_hours: float
    part_lines: list
    estimated_total_cents: int
    final_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LockPart(TypedDict):
    id: str
    sku: str
    part_status: str
    restricted_blank: bool
    units_total: int
    units_available: int
    units_reserved: int
    units_committed: int
    created_at: str
    updated_at: str
    version: int


class PartReservation(TypedDict):
    id: str
    on_site_quote_id: str
    lock_part_id: str
    quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    service_job_id: str
    captured_amount_cents: int
    refunded_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    service_job_id: str
    filed_at_minute: int
    days_since_close: int
    reason: str
    refund_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only compliance record (common_fields:false) — only id + created_at.
class KeyAuthorizationRecord(TypedDict):
    id: str
    service_job_id: str
    auth_kind: str
    authorizing_party: str
    id_document_ref: str
    created_at: str
