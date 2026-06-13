"""Domain types for the Car Wash Membership API: entity TypedDicts, status enums, role enum.

All field names and status values are taken verbatim from the PRD.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ──────────────────────────────────────────────────────────

class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AccountType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FLEET = "FLEET"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PlanTier(str, Enum):
    UNLIMITED = "UNLIMITED"
    SINGLE_WASH = "SINGLE_WASH"


class LocationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    FROZEN = "FROZEN"
    CANCEL_SCHEDULED = "CANCEL_SCHEDULED"
    CANCELLED = "CANCELLED"


class MembershipAddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DETACHED = "DETACHED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    WRITTEN_OFF = "WRITTEN_OFF"
    VOID = "VOID"


class InvoiceKind(str, Enum):
    CYCLE = "CYCLE"
    PRORATION = "PRORATION"
    TOPUP = "TOPUP"


class WashEventStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ADMITTED = "ADMITTED"
    REJECTED = "REJECTED"
    COMPLETED = "COMPLETED"


class WalletReason(str, Enum):
    CANCEL_REFUND = "CANCEL_REFUND"
    FREEZE_REFUND = "FREEZE_REFUND"
    TOPUP_DEBIT = "TOPUP_DEBIT"
    INVOICE_CHARGE = "INVOICE_CHARGE"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"


class FreezeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_HOLDER = "AccountHolder"
    LOCATION_OPERATOR = "LocationOperator"
    BILLING_ADMIN = "BillingAdmin"


# ─── Entity TypedDicts ─────────────────────────────────────────────────────
# Entities carrying the common fields (id, created_at, updated_at, version).

class Account(TypedDict):
    id: str
    account_type: str
    company_name: Optional[str]
    contact_email: str
    status: str
    wallet_balance_cents: int
    active_vehicle_count: int
    fleet_discount_pct: float
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    name: str
    tier_type: str
    monthly_fee_cents: int
    included_credits: int
    per_credit_price_cents: int
    wash_cooldown_hours: int
    max_addons: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Location(TypedDict):
    id: str
    name: str
    state_code: str
    in_network: bool
    daily_wash_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    name: str
    recurring_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict):
    id: str
    account_id: str
    license_plate: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Membership(TypedDict):
    id: str
    account_id: str
    vehicle_id: str
    plan_id: str
    status: str
    cycle_anchor_utc: Optional[str]
    current_cycle_paid_cents: int
    credit_balance: int
    credits_granted: int
    credits_consumed: int
    last_admitted_wash_utc: Optional[str]
    freeze_count: int
    created_at: str
    updated_at: str
    version: int


class MembershipAddOn(TypedDict):
    id: str
    membership_id: str
    addon_id: str
    status: str
    locked_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    membership_id: str
    status: str
    kind: str
    base_fee_cents: int
    addon_fee_cents: int
    discount_cents: int
    total_cents: int
    attempt_count: int
    created_at: str
    updated_at: str
    version: int


class Freeze(TypedDict):
    id: str
    membership_id: str
    start_utc: str
    end_utc: str
    status: str
    refund_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only audit entities (id + created_at only) ─────────────────────
# WashEvent and WalletTransaction are immutable records: no updated_at, no version.

class WashEvent(TypedDict):
    id: str
    membership_id: Optional[str]
    vehicle_id: Optional[str]
    location_id: str
    license_plate: str
    state_code: str
    status: str
    rejection_error_id: Optional[str]
    consumed_credit: bool
    admitted_at_utc: Optional[str]
    created_at: str


class WalletTransaction(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    reason: str
    related_invoice_id: Optional[str]
    balance_after_cents: int
    created_at: str
