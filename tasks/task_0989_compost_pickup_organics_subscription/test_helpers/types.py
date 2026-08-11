"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class SubscriberType(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"


class BinType(str, Enum):
    BIN_35L = "BIN_35L"
    BIN_70L = "BIN_70L"
    BIN_240L = "BIN_240L"
    BIN_960L = "BIN_960L"


class AccountStanding(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    DELINQUENT = "DELINQUENT"


class ServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class BinStatus(str, Enum):
    IN_DEPOT = "IN_DEPOT"
    AT_CUSTOMER = "AT_CUSTOMER"


class BinCondition(str, Enum):
    CLEAN = "CLEAN"
    NEEDS_WASH = "NEEDS_WASH"


class PickupStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    SKIPPED = "SKIPPED"
    MISSED = "MISSED"
    REJECTED_CONTAMINATION = "REJECTED_CONTAMINATION"
    CANCELLED_SYSTEM = "CANCELLED_SYSTEM"
    VOIDED = "VOIDED"


class TagSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TagCategory(str, Enum):
    PLASTIC = "PLASTIC"
    GLASS = "GLASS"
    METAL = "METAL"
    LIQUIDS = "LIQUIDS"
    OTHER = "OTHER"


class TagStatus(str, Enum):
    TAGGED = "TAGGED"
    DISPUTED = "DISPUTED"
    CONFIRMED = "CONFIRMED"
    WAIVED = "WAIVED"


class WeighTicketStatus(str, Enum):
    POSTED = "POSTED"


class EntryType(str, Enum):
    EARNED_ESTIMATED = "EARNED_ESTIMATED"
    EARNED_FINAL_ADJUSTMENT = "EARNED_FINAL_ADJUSTMENT"
    REDEMPTION_DEBIT = "REDEMPTION_DEBIT"
    INVOICE_APPLICATION_DEBIT = "INVOICE_APPLICATION_DEBIT"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    REVERSAL = "REVERSAL"


class RedemptionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class Weekday(str, Enum):
    MON = "MON"
    TUE = "TUE"
    WED = "WED"
    THU = "THU"
    FRI = "FRI"
    SAT = "SAT"
    SUN = "SUN"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    SUBSCRIBER = "Subscriber"
    DRIVER = "Driver"
    OPERATIONS_MANAGER = "OperationsManager"


# --- Entity shapes -----------------------------------------------------------
# ServicePlan is configuration: it carries only id + created_at (PRD §2.5).
class ServicePlan(TypedDict, total=False):
    id: str
    created_at: str
    code: str
    name: str
    subscriber_type: str
    bin_type: str
    included_bins: int
    weekly_price_cents: int
    metered_base_cents: int
    per_kg_rate_cents: int
    included_kg_per_week: float
    credit_rate_cents_per_kg: int
    skip_allowance_per_quarter: int


class Subscriber(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    email: str
    full_name: str
    subscriber_type: str
    address: str
    account_standing: str
    credit_balance_cents: int


class Subscription(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscriber_id: str
    plan_id: str
    route_id: str
    start_date: str
    service_status: str
    strike_count: int
    skips_used_this_quarter: int
    current_quarter: Optional[str]
    pause_windows: list


class Route(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    code: str
    weekday: str
    max_stops: int
    active_subscriptions_count: int


class Bin(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    bin_type: str
    nominal_capacity_kg: float
    status: str
    condition: str
    current_subscription_id: Optional[str]


class PickupEvent(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscription_id: str
    route_id: str
    service_date: str
    status: str
    fullness_pct: Optional[float]
    estimated_kg: Optional[float]
    final_kg: Optional[float]
    collected_bin_id: Optional[str]
    replacement_bin_id: Optional[str]


class ContaminationTag(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    pickup_id: str
    subscription_id: str
    severity: str
    category: str
    note: Optional[str]
    tagged_by_driver_id: str
    status: str
    surcharge_cents: Optional[int]
    resolved_by: Optional[str]
    resolved_at: Optional[str]


class WeighTicket(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    route_id: str
    service_date: str
    gross_kg: float
    tare_kg: float
    net_kg: float
    status: str


# CompostCreditEntry is an append-only ledger event: only id + created_at (PRD §2.5).
class CompostCreditEntry(TypedDict, total=False):
    id: str
    created_at: str
    subscriber_id: str
    pickup_id: Optional[str]
    redemption_id: Optional[str]
    invoice_id: Optional[str]
    entry_type: str
    amount_cents: int
    reason: Optional[str]
    season: str


class CreditRedemption(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscriber_id: str
    bags: int
    total_kg: float
    total_cents: int
    status: str


class Invoice(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    subscriber_id: str
    week_start_date: str
    lines: list
    subtotal_cents: int
    credit_applied_cents: int
    total_cents: int
    status: str
    due_date: str
