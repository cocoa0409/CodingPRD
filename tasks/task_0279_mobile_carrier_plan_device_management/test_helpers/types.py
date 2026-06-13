"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Mobile Carrier Plan & Device Management PRD (§2.5, §3).
Charge and UsageRecord are append-only ledger events (id + created_at only);
all other entities carry the common id/created_at/updated_at/version set.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Status enumerations (PRD §3) ─────────────────────────────────────────

class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DeviceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"


class LineStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class SuspendReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    NONPAYMENT = "NONPAYMENT"
    LOST_STOLEN = "LOST_STOLEN"


class SimType(str, Enum):
    PHYSICAL = "PHYSICAL"
    ESIM = "ESIM"


class SimStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVATED = "ACTIVATED"
    DEACTIVATED = "DEACTIVATED"


class InstallmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    CANCELLED = "CANCELLED"


class AddOnType(str, Enum):
    ROAMING_DAYPASS = "ROAMING_DAYPASS"
    INTL_MONTHLY = "INTL_MONTHLY"


class AddOnStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PortDirection(str, Enum):
    PORT_IN = "PORT_IN"
    PORT_OUT = "PORT_OUT"


class PortStatus(str, Enum):
    REQUESTED = "REQUESTED"
    VALIDATED = "VALIDATED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    REVERTED = "REVERTED"


class PortRejectReason(str, Enum):
    PIN_MISMATCH = "PIN_MISMATCH"
    NUMBER_NOT_PORTABLE = "NUMBER_NOT_PORTABLE"
    DONOR_REFUSED = "DONOR_REFUSED"


class UpgradeStatus(str, Enum):
    COMPLETED = "COMPLETED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ChargeType(str, Enum):
    PLAN_BASE = "PLAN_BASE"
    OVERAGE = "OVERAGE"
    EIP_INSTALLMENT = "EIP_INSTALLMENT"
    ADDON = "ADDON"
    EIP_PAYOFF = "EIP_PAYOFF"
    CREDIT = "CREDIT"


class UsageType(str, Enum):
    DATA = "DATA"
    VOICE = "VOICE"
    TEXT = "TEXT"


class UserRole(str, Enum):
    CARRIER_AGENT = "CarrierAgent"
    SUBSCRIBER = "Subscriber"
    PORTING_OPS = "PortingOps"
    BILLING_SYSTEM = "BillingSystem"


# ─── Entity TypedDicts (PRD §2.5, §3) ─────────────────────────────────────
# Entities below carry common fields: id, created_at, updated_at, version.

class Account(TypedDict):
    id: str
    holder_name: str
    holder_email: str
    billing_day_of_month: int
    status: str
    active_line_count: int
    group_discount_pct: float
    total_eip_outstanding_cents: int
    wallet_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict):
    id: str
    code: str
    name: str
    monthly_fee_cents: int
    included_data_mb: int
    overage_tier1_cap_mb: int
    overage_tier1_rate_milli_cents: int
    overage_tier2_rate_milli_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict):
    id: str
    model: str
    sku: str
    retail_price_cents: int
    stock_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Line(TypedDict):
    id: str
    account_id: str
    plan_id: str
    phone_number: Optional[str]
    sim_type: str
    status: str
    suspend_reason: Optional[str]
    cycle_data_used_mb: int
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SimAssignment(TypedDict):
    id: str
    line_id: str
    sim_type: str
    iccid: Optional[str]
    esim_activation_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InstallmentPlan(TypedDict):
    id: str
    line_id: str
    device_id: str
    term_months: int
    down_payment_cents: int
    financed_cents: int
    monthly_installment_cents: int
    remaining_balance_cents: int
    installments_paid: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AddOn(TypedDict):
    id: str
    line_id: str
    addon_type: str
    daily_fee_cents: Optional[int]
    monthly_fee_cents: Optional[int]
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PortRequest(TypedDict):
    id: str
    line_id: str
    direction: str
    external_number: str
    donor_carrier: str
    account_pin: str
    status: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UpgradeOrder(TypedDict):
    id: str
    line_id: str
    old_installment_plan_id: str
    new_device_id: str
    new_term_months: int
    new_down_payment_cents: int
    trade_in_credit_cents: int
    payoff_charge_cents: int
    new_installment_plan_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingCycle(TypedDict):
    id: str
    account_id: str
    cycle_start: str
    cycle_end: str
    days_in_cycle: int
    total_charges_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only ledger events: id + created_at only (PRD §2.5).

class Charge(TypedDict):
    id: str
    billing_cycle_id: str
    line_id: Optional[str]
    charge_type: str
    amount_cents: int
    memo: str
    created_at: str


class UsageRecord(TypedDict):
    id: str
    line_id: str
    usage_type: str
    data_mb: int
    occurred_at: str
    created_at: str
