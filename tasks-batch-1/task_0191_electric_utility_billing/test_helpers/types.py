"""Domain types for the Electric Utility Billing API: entity TypedDicts,
status enums, and the role enum. Field sets follow the PRD's resource
definitions (§2.4, §3). Resources that carry only `id` and `created_at`
(MeterRead, SystemClock) deliberately omit `updated_at` and `version`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class TariffStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AccountServiceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONNECT_PENDING = "DISCONNECT_PENDING"
    DISCONNECTED = "DISCONNECTED"
    RECONNECT_PENDING = "RECONNECT_PENDING"


class AccountFinancialStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    IN_ARREARS = "IN_ARREARS"


class MeterType(str, Enum):
    CONSUMPTION_ONLY = "CONSUMPTION_ONLY"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class MeterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class TouPeriod(str, Enum):
    ON_PEAK = "ON_PEAK"
    MID_PEAK = "MID_PEAK"
    OFF_PEAK = "OFF_PEAK"


class BillStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    VOID = "VOID"


class PaymentMethod(str, Enum):
    ACH = "ACH"
    CARD = "CARD"
    CASH = "CASH"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class ServiceOrderType(str, Enum):
    DISCONNECT = "DISCONNECT"
    RECONNECT = "RECONNECT"


class ServiceOrderStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ServiceOrderReason(str, Enum):
    NONPAY = "NONPAY"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"
    RESTORE_AFTER_PAYMENT = "RESTORE_AFTER_PAYMENT"


class BudgetPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRUED_UP = "TRUED_UP"
    CANCELLED = "CANCELLED"


class AssistanceProgram(str, Enum):
    LIHEAP = "LIHEAP"
    EMERGENCY_CRISIS = "EMERGENCY_CRISIS"


class AssistanceGrantStatus(str, Enum):
    PLEDGED = "PLEDGED"
    APPLIED = "APPLIED"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    BILLING_OPERATOR = "BillingOperator"
    FIELD_DISPATCHER = "FieldDispatcher"
    ASSISTANCE_CASEWORKER = "AssistanceCaseworker"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true → id/created_at/updated_at/version)
# ---------------------------------------------------------------------------
class Tariff(TypedDict):
    id: str
    code: str
    name: str
    status: str
    fixed_charge_cents: int
    tier_breakpoints_kwh: List[float]
    tier_rates_cents_per_kwh: List[int]
    tou_multipliers: dict
    demand_charge_cents_per_kw: int
    net_metering_credit_cents_per_kwh: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict):
    id: str
    tariff_id: str
    holder_name: str
    service_status: str
    financial_status: str
    balance_cents: int
    net_metering_credit_balance_cents: int
    oldest_unpaid_bill_due_date: Optional[str]
    budget_plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Meter(TypedDict):
    id: str
    account_id: str
    serial: str
    meter_type: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Bill(TypedDict):
    id: str
    account_id: str
    tariff_id: str
    period_start: str
    period_end: str
    status: str
    total_import_kwh: float
    total_export_kwh: float
    billed_peak_demand_kw: float
    energy_charge_cents: int
    demand_charge_cents: int
    net_metering_credit_applied_cents: int
    assistance_applied_cents: int
    total_due_cents: int
    amount_paid_cents: int
    due_date: str
    is_budget_billed: bool
    actual_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    account_id: str
    amount_cents: int
    method: str
    status: str
    allocations: List[dict]
    created_at: str
    updated_at: str
    version: int


class ServiceOrder(TypedDict):
    id: str
    account_id: str
    order_type: str
    status: str
    reason: str
    created_at: str
    updated_at: str
    version: int


class BudgetBillingPlan(TypedDict):
    id: str
    account_id: str
    status: str
    levelized_amount_cents: int
    accumulated_actual_cents: int
    accumulated_levelized_cents: int
    true_up_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class AssistanceGrant(TypedDict):
    id: str
    account_id: str
    program: str
    status: str
    pledged_cents: int
    remaining_cents: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Lean resources (common_fields: false → id + created_at only)
# ---------------------------------------------------------------------------
class MeterRead(TypedDict):
    id: str
    meter_id: str
    interval_start: str
    interval_end: str
    import_kwh: float
    export_kwh: float
    tou_period: str
    avg_demand_kw: float
    created_at: str


class SystemClock(TypedDict):
    id: str
    current_utc: str
    created_at: str
