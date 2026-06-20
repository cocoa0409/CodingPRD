"""Domain types: entity TypedDicts, status enums, role enum for the gas-utility-billing API."""
from enum import Enum
from typing import TypedDict, Optional


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    BILLING_ADMIN = "BillingAdmin"
    CUSTOMER_SERVICE = "CustomerService"
    FIELD_TECH = "FieldTech"
    ACCOUNT = "Account"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CustomerClass(str, Enum):
    RESIDENTIAL = "RESIDENTIAL"
    COMMERCIAL = "COMMERCIAL"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHUTOFF_PENDING = "SHUTOFF_PENDING"
    DISCONNECTED = "DISCONNECTED"
    FINALED = "FINALED"


class LowIncomeStatus(str, Enum):
    NONE = "NONE"
    ENROLLED = "ENROLLED"


class LowIncomeTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class MeterUom(str, Enum):
    CCF = "CCF"
    THERM = "THERM"


class MeterStatus(str, Enum):
    PENDING_SET = "PENDING_SET"
    SET = "SET"
    LOCKED = "LOCKED"
    REMOVED = "REMOVED"


class MeterReadType(str, Enum):
    ACTUAL = "ACTUAL"
    ESTIMATED = "ESTIMATED"


class MeterReadStatus(str, Enum):
    POSTED = "POSTED"
    VOID = "VOID"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"
    CORRECTED = "CORRECTED"


class BudgetPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRUED_UP = "TRUED_UP"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ServiceOrderType(str, Enum):
    METER_SET = "METER_SET"
    SHUTOFF = "SHUTOFF"
    RECONNECT = "RECONNECT"


class ServiceOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class TicketKind(str, Enum):
    ODOR = "ODOR"
    LEAK = "LEAK"
    CARBON_MONOXIDE = "CARBON_MONOXIDE"


class TicketSeverity(str, Enum):
    GRADE_1 = "GRADE_1"
    GRADE_2 = "GRADE_2"
    GRADE_3 = "GRADE_3"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    DISPATCHED = "DISPATCHED"
    MADE_SAFE = "MADE_SAFE"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class DepositReason(str, Enum):
    NEW_SERVICE = "NEW_SERVICE"
    RECONNECT = "RECONNECT"
    DELINQUENCY = "DELINQUENCY"


class DepositStatus(str, Enum):
    REQUIRED = "REQUIRED"
    HELD = "HELD"
    WAIVED = "WAIVED"
    REFUNDED = "REFUNDED"
    APPLIED = "APPLIED"


class LowIncomeCreditStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------
# common_fields: true entities carry id, created_at, updated_at, version.
class RateSchedule(TypedDict):
    id: str
    code: str
    customer_class: str
    fixed_customer_charge_cents: int
    distribution_rate_cents_per_therm: int
    btu_factor: float
    minimum_bill_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class PgaSchedule(TypedDict):
    id: str
    effective_month: str
    customer_class: str
    commodity_rate_cents_per_therm: int
    supplier_refund_cents_per_therm: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    rate_schedule_id: str
    customer_class: str
    holder_name: str
    service_status: str
    low_income_status: str
    low_income_tier: str
    budget_enrolled: bool
    balance_cents: int
    past_due_cents: int
    deposit_held_cents: int
    consecutive_ontime_payments: int
    shutoff_eligible: bool
    created_at: str
    updated_at: str
    version: int


class PremiseMeter(TypedDict):
    id: str
    account_id: str
    serial_no: str
    uom: str
    status: str
    install_index: float
    last_index: float
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at (no updated_at / version).
class MeterRead(TypedDict):
    id: str
    premise_meter_id: str
    account_id: str
    read_date: str
    reading_index: float
    read_type: str
    status: str
    ccf_consumed: float
    therms_consumed: float
    bill_id: Optional[str]
    created_at: str


class Bill(TypedDict):
    id: str
    account_id: str
    service_month: str
    from_read_id: Optional[str]
    to_read_id: str
    corrects_bill_id: Optional[str]
    therms_billed: float
    commodity_charge_cents: int
    distribution_charge_cents: int
    fixed_charge_cents: int
    low_income_credit_cents: int
    amount_due_cents: int
    budget_billed_cents: int
    status: str
    due_date: Optional[str]
    paid_cents: int
    created_at: str
    updated_at: str
    version: int


class BudgetPlan(TypedDict):
    id: str
    account_id: str
    anchor_month: str
    monthly_installment_cents: int
    projected_annual_cents: int
    accrued_actual_cents: int
    accrued_budget_cents: int
    status: str
    trueup_balance_cents: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only.
class Payment(TypedDict):
    id: str
    account_id: str
    bill_id: str
    amount_cents: int
    posted_date: str
    status: str
    on_time: bool
    created_at: str


class ServiceOrder(TypedDict):
    id: str
    account_id: str
    premise_meter_id: Optional[str]
    order_type: str
    status: str
    scheduled_date: Optional[str]
    completed_index: Optional[float]
    created_at: str
    updated_at: str
    version: int


class EmergencyTicket(TypedDict):
    id: str
    account_id: Optional[str]
    premise_meter_id: str
    kind: str
    severity: str
    reported_indoors: bool
    status: str
    response_due_minutes: int
    gas_locked: bool
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LowIncomeCredit(TypedDict):
    id: str
    account_id: str
    household_size: int
    annual_income_cents: int
    tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — singleton clock.
class Clock(TypedDict):
    current_utc: str
    heating_season_active: bool
