"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Waste Recycling Collection PRD. Money is integer cents,
weights are numbers (pounds), percentages are numbers.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    RESIDENT_ACCOUNT = "ResidentAccount"
    DISPATCHER = "Dispatcher"
    DRIVER = "Driver"
    BILLING = "Billing"


# ─── Status enums ─────────────────────────────────────
class ServiceAccountStatus(str, Enum):
    PENDING_SETUP = "PENDING_SETUP"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CartStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    RETIRED = "RETIRED"


class ServicePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    TERMINATED = "TERMINATED"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StopStatus(str, Enum):
    PENDING = "PENDING"
    SERVICED = "SERVICED"
    SKIPPED = "SKIPPED"


class PickupOutcome(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CANCELLED = "CANCELLED"


class MissReason(str, Enum):
    BLOCKED_ACCESS = "BLOCKED_ACCESS"
    NOT_OUT = "NOT_OUT"
    TRUCK_FULL = "TRUCK_FULL"
    MISSED_BY_CREW = "MISSED_BY_CREW"


class ContaminationTagStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"


class ContaminationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    REJECT = "REJECT"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    VOID = "VOID"


class SpecialPickupKind(str, Enum):
    BULK = "BULK"
    HAZARDOUS = "HAZARDOUS"


class HazardClass(str, Enum):
    FLAMMABLE = "FLAMMABLE"
    CORROSIVE = "CORROSIVE"
    TOXIC = "TOXIC"
    EWASTE = "EWASTE"


class SpecialPickupStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MissedPickupCreditStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    VOID = "VOID"


class CreditSourceType(str, Enum):
    PICKUP = "PICKUP"
    SPECIAL_PICKUP = "SPECIAL_PICKUP"


class DiversionPeriodStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class RateClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL_SMALL = "COMMERCIAL_SMALL"
    COMMERCIAL_LARGE = "COMMERCIAL_LARGE"


class Stream(str, Enum):
    TRASH = "TRASH"
    RECYCLE = "RECYCLE"
    ORGANICS = "ORGANICS"


class Frequency(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    MONTHLY = "MONTHLY"


# ─── Entity TypedDicts ────────────────────────────────
# Entities with full common-field quartet (id, created_at, updated_at, version).

class ServiceAccount(TypedDict):
    id: str
    service_address: str
    rate_class: str
    status: str
    account_balance_cents: int
    diversion_floor_pct: float
    created_at: str
    updated_at: str
    version: int


class Cart(TypedDict):
    id: str
    account_id: str
    stream: str
    size_gallons: int
    status: str
    tare_weight_lbs: float
    created_at: str
    updated_at: str
    version: int


class ServicePlan(TypedDict):
    id: str
    account_id: str
    stream: str
    frequency: str
    base_monthly_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict):
    id: str
    service_date: str
    stream: str
    status: str
    assigned_driver_id: Optional[str]
    total_net_weight_lbs: float
    created_at: str
    updated_at: str
    version: int


class Stop(TypedDict):
    id: str
    route_id: str
    account_id: str
    sequence: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Pickup(TypedDict):
    id: str
    stop_id: str
    cart_id: str
    outcome: str
    miss_reason: Optional[str]
    contaminated: bool
    created_at: str
    updated_at: str
    version: int


class ContaminationTag(TypedDict):
    id: str
    pickup_id: str
    severity: str
    status: str
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    period_start: str
    period_end: str
    status: str
    base_fee_cents: int
    weight_charge_cents: int
    contamination_surcharge_cents: int
    credit_cents: int
    total_cents: int
    diversion_penalty_cents: int
    balance_cents: int
    created_at: str
    updated_at: str
    version: int


class SpecialPickup(TypedDict):
    id: str
    account_id: str
    kind: str
    requested_date: str
    hazard_class: Optional[str]
    status: str
    quoted_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class MissedPickupCredit(TypedDict):
    id: str
    account_id: str
    source_type: str
    source_pickup_id: Optional[str]
    source_special_pickup_id: Optional[str]
    amount_cents: int
    status: str
    applied_invoice_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiversionPeriod(TypedDict):
    id: str
    account_id: str
    period_start: str
    period_end: str
    status: str
    diverted_weight_lbs: float
    total_weight_lbs: float
    diversion_rate_pct: float
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable scale record. ONLY id + created_at
# (plus its entity-specific fields). NO updated_at, NO version.
class WeightTicket(TypedDict):
    id: str
    pickup_id: str
    gross_weight_lbs: float
    net_weight_lbs: float
    diverted: bool
    created_at: str
