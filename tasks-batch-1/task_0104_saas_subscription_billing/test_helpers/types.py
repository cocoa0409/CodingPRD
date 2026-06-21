"""Domain types: entity TypedDicts, status enums, role enum.

Field sets mirror the PRD's resource definitions. Every entity except
UsageRecord carries the full id/created_at/updated_at/version set; the
append-only UsageRecord carries only id and created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────
class UserRole(str, Enum):
    BILLING_ADMIN = "BillingAdmin"
    ACCOUNT_OWNER = "AccountOwner"
    ANONYMOUS = "Anonymous"


# ─── Status / enum dimensions ─────────────────────────
class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class CouponStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"


class CouponDiscountType(str, Enum):
    PERCENT = "PERCENT"
    FIXED = "FIXED"


class CouponDuration(str, Enum):
    ONCE = "ONCE"
    RECURRING = "RECURRING"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class SubscriptionLifecycleStatus(str, Enum):
    TRIALING = "TRIALING"
    ACTIVE = "ACTIVE"
    CANCELED = "CANCELED"


class SubscriptionBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    UNPAID = "UNPAID"


class SubscriptionAddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class PauseWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELED = "CANCELED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    VOID = "VOID"


class InvoiceLineKind(str, Enum):
    SUBSCRIPTION = "SUBSCRIPTION"
    ADDON = "ADDON"
    OVERAGE = "OVERAGE"
    PRORATION_CREDIT = "PRORATION_CREDIT"
    PRORATION_CHARGE = "PRORATION_CHARGE"


class PaymentStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    FAILED = "FAILED"


# ─── Entity TypedDicts (common_fields: true) ──────────
class Plan(TypedDict):
    id: str
    tier: str
    monthly_fee_cents: int
    included_usage_units: int
    overage_tiers: List[dict]
    trial_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanPriceSchedule(TypedDict):
    id: str
    plan_id: str
    monthly_fee_cents: int
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    code: str
    monthly_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict):
    id: str
    code: str
    discount_type: str
    percent_off: Optional[int]
    amount_off_cents: Optional[int]
    duration: str
    max_redemptions: int
    redemption_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxJurisdiction(TypedDict):
    id: str
    region_code: str
    tax_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    email: str
    company_name: str
    region_code: str
    tax_jurisdiction_id: str
    payment_method_ok: bool
    mrr_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict):
    id: str
    account_id: str
    plan_id: str
    coupon_id: Optional[str]
    period_start: str
    period_end: str
    trial_end: Optional[str]
    lifecycle_status: str
    billing_status: str
    dunning_attempt: int
    next_retry_at: Optional[str]
    mrr_contribution_cents: int
    created_at: str
    updated_at: str
    version: int


class SubscriptionAddOn(TypedDict):
    id: str
    subscription_id: str
    addon_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPauseWindow(TypedDict):
    id: str
    subscription_id: str
    pause_from: str
    pause_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    account_id: str
    subscription_id: str
    coupon_id: Optional[str]
    tax_jurisdiction_id: str
    subtotal_cents: int
    discount_cents: int
    tax_cents: int
    total_cents: int
    amount_paid_cents: int
    period_start: str
    period_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    id: str
    invoice_id: str
    kind: str
    description: str
    amount_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    attempt_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RevenueScheduleEntry(TypedDict):
    id: str
    invoice_id: str
    subscription_id: str
    service_period_start: str
    service_period_end: str
    total_recognizable_cents: int
    recognized_to_date_cents: int
    created_at: str
    updated_at: str
    version: int


# ─── Append-only entity (common_fields: false) ────────
# UsageRecord carries ONLY id + created_at — no updated_at, no version.
class UsageRecord(TypedDict):
    id: str
    subscription_id: str
    units: int
    recorded_at: str
    billed: bool
    created_at: str
