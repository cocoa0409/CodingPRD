"""Domain types: entity TypedDicts, status enums, role enum.

All field names and status values are taken verbatim from the Water & Sewer
Utility Billing PRD (sections 2 and 3).
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BILLING_CLERK = "BillingClerk"
    FIELD_OPS = "FieldOps"
    ASSISTANCE_CASEWORKER = "AssistanceCaseworker"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Status enums (PRD §2.4, §3.x)
# ---------------------------------------------------------------------------
class AccountBillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    SHUTOFF_PENDING = "SHUTOFF_PENDING"
    DELINQUENT_PROTECTED = "DELINQUENT_PROTECTED"


class AccountServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RESTORED = "RESTORED"


class MeterType(str, Enum):
    POTABLE = "POTABLE"
    IRRIGATION = "IRRIGATION"


class MeterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class MeterReadSource(str, Enum):
    AMI = "AMI"
    MANUAL = "MANUAL"


class BillingCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    PAID = "PAID"
    VOID = "VOID"


class BudgetBillingPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRUED_UP = "TRUED_UP"
    CANCELLED = "CANCELLED"


class AssistanceEnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LeakAdjustmentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ShutoffOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    RECONNECTED = "RECONNECTED"
    CANCELLED = "CANCELLED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CASH = "CASH"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Full-record entities (PRD §2.4) carry id/created_at/updated_at/version.
# Append-only entities (MeterRead, Payment) carry ONLY id + created_at.
# ---------------------------------------------------------------------------
class RateSchedule(TypedDict):
    id: str
    name: str
    fixed_water_charge_cents: int
    fixed_sewer_charge_cents: int
    water_tiers: List[dict]
    sewer_rate_cents_per_kgal: int
    sewer_ratio_pct: int
    sewer_cap_gallons: Optional[int]
    leak_adjustment_rate_pct: int
    assistance_discount_pct: int
    arrears_shutoff_threshold_cents: int
    reconnect_fee_cents: int
    late_fee_pct: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    rate_schedule_id: str
    holder_name: str
    service_address: str
    billing_status: str
    service_status: str
    balance_due_cents: int
    past_due_cents: int
    budget_billing_enrolled: bool
    assistance_enrolled: bool
    created_at: str
    updated_at: str
    version: int


class Meter(TypedDict):
    id: str
    account_id: str
    meter_type: str
    serial: str
    last_reading_gallons: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only (PRD §2.4, §3.2)
class MeterRead(TypedDict):
    id: str
    meter_id: str
    reading_gallons: int
    read_date: str
    source: str
    consumption_gallons: int
    created_at: str


class BillingCycle(TypedDict):
    id: str
    label: str
    period_start: str
    period_end: str
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict):
    id: str
    account_id: str
    billing_cycle_id: str
    rate_schedule_id: str
    potable_consumption_gallons: int
    irrigation_consumption_gallons: int
    billable_sewer_gallons: int
    fixed_charge_cents: int
    water_volumetric_cents: int
    sewer_volumetric_cents: int
    leak_credit_cents: int
    amount_billed_cents: int
    total_cents: int
    budget_billing_amount_cents: int
    status: str
    late_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class BudgetBillingPlan(TypedDict):
    id: str
    account_id: str
    monthly_amount_cents: int
    anchor_balance_cents: int
    cycles_elapsed: int
    trued_up_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssistanceEnrollment(TypedDict):
    id: str
    account_id: str
    program_code: str
    certified_until: str
    grants_shutoff_protection: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class LeakAdjustment(TypedDict):
    id: str
    bill_id: str
    account_id: str
    baseline_gallons: int
    repair_evidence_ref: str
    credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShutoffOrder(TypedDict):
    id: str
    account_id: str
    triggering_bill_id: str
    scheduled_for: str
    reconnect_fee_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: id + created_at only (PRD §2.4, §3.6)
class Payment(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    applied_to_bill_id: Optional[str]
    method: str
    created_at: str


class Moratorium(TypedDict):
    id: str
    label: str
    window_start: str
    window_end: str
    active: bool
    created_at: str
    updated_at: str
    version: int
