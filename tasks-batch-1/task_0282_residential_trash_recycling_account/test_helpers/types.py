"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    ACCOUNT_HOLDER = "AccountHolder"
    CREW_LEAD = "CrewLead"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class AccountStatus(str, Enum):
    PENDING_START = "PENDING_START"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    STOPPED = "STOPPED"
    TRANSFERRED_OUT = "TRANSFERRED_OUT"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    IN_COLLECTIONS = "IN_COLLECTIONS"


class CartType(str, Enum):
    TRASH = "TRASH"
    RECYCLING = "RECYCLING"


class CartStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class Stream(str, Enum):
    TRASH = "TRASH"
    RECYCLING = "RECYCLING"


class ScheduleStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class PickupOutcome(str, Enum):
    COLLECTED = "COLLECTED"
    MISSED = "MISSED"
    CONTAMINATED = "CONTAMINATED"


class ExtraPickupStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    VOID = "VOID"


class PaymentMethod(str, Enum):
    MANUAL = "MANUAL"
    AUTOPAY = "AUTOPAY"


class PaymentStatus(str, Enum):
    APPLIED = "APPLIED"


class CreditStatus(str, Enum):
    ISSUED = "ISSUED"
    APPLIED = "APPLIED"
    EXPIRED = "EXPIRED"


class ContaminationStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    WAIVED = "WAIVED"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"


class ShiftDirection(str, Enum):
    DELAY_ONE_DAY = "DELAY_ONE_DAY"
    NONE = "NONE"


class RecyclingParity(str, Enum):
    EVEN = "EVEN"
    ODD = "ODD"


# --------------------------------------------------------------------------
# Entity TypedDicts
#   All first-class records carry id/created_at/updated_at/version.
#   Holiday is the sole exception: id + created_at only.
# --------------------------------------------------------------------------
class ServicePlan(TypedDict):
    id: str
    tier: str
    trash_cart_size_gallons: int
    recycling_cart_size_gallons: int
    monthly_base_cents: int
    extra_cart_monthly_cents: int
    extra_pickup_base_cents: int
    bulk_item_cents: int
    archived: bool
    created_at: str
    updated_at: str
    version: int


class ServiceAccount(TypedDict):
    id: str
    plan_id: str
    zone_id: str
    service_address: str
    holder_name: str
    status: str
    billing_status: str
    autopay_enabled: bool
    stored_payment_token: Optional[str]
    account_balance_cents: int
    credit_balance_cents: int
    service_start_date: Optional[str]
    transferred_from_account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CollectionZone(TypedDict):
    id: str
    name: str
    base_pickup_weekday: int
    recycling_week_parity: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable, carries ONLY id + created_at
class Holiday(TypedDict):
    id: str
    zone_id: str
    holiday_date: str
    shift_direction: str
    created_at: str


class CartAssignment(TypedDict):
    id: str
    account_id: str
    cart_type: str
    size_gallons: int
    is_extra: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupSchedule(TypedDict):
    id: str
    account_id: str
    service_date: str
    stream: str
    effective_pickup_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PickupEvent(TypedDict):
    id: str
    schedule_id: str
    outcome: str
    reported_at: str
    created_at: str
    updated_at: str
    version: int


class ExtraPickupRequest(TypedDict):
    id: str
    account_id: str
    requested_date: str
    bulk_item_count: int
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    period_start: str
    period_end: str
    gross_amount_cents: int
    credit_applied_cents: int
    amount_due_cents: int
    due_date: str
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


class MissedPickupCredit(TypedDict):
    id: str
    account_id: str
    pickup_event_id: str
    amount_cents: int
    applied_invoice_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ContaminationNotice(TypedDict):
    id: str
    account_id: str
    pickup_event_id: str
    severity: str
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
