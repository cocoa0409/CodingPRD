"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    SERVICE_MANAGER = "ServiceManager"
    TECHNICIAN = "Technician"
    WINDING_TECHNICIAN = "WindingTechnician"
    ESTIMATOR = "Estimator"
    CUSTOMER = "Customer"


class MotorCustody(str, Enum):
    WITH_CUSTOMER = "WITH_CUSTOMER"
    IN_SHOP = "IN_SHOP"
    IN_POOL = "IN_POOL"
    ON_LOAN = "ON_LOAN"


class CustomerStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    HOLD = "HOLD"


class WorkOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    INCOMING_TEST = "INCOMING_TEST"
    DIAGNOSED = "DIAGNOSED"
    QUOTED = "QUOTED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    IN_REWIND = "IN_REWIND"
    BALANCING = "BALANCING"
    FINAL_TEST = "FINAL_TEST"
    READY_FOR_PICKUP = "READY_FOR_PICKUP"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    DECLINED = "DECLINED"
    SCRAPPED = "SCRAPPED"


class WorkOrderPriority(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"
    EMERGENCY = "EMERGENCY"


class TestKind(str, Enum):
    INCOMING = "INCOMING"
    CORE_LOSS = "CORE_LOSS"
    FINAL = "FINAL"


class TestVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class QuoteVariant(str, Enum):
    AS_QUOTED = "AS_QUOTED"
    TCO_ADJUSTED = "TCO_ADJUSTED"


class Recommendation(str, Enum):
    REWIND = "REWIND"
    REPLACE = "REPLACE"


class CoilConnection(str, Enum):
    WYE = "WYE"
    DELTA = "DELTA"


class PoolContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PoolLoanStatus(str, Enum):
    OUT = "OUT"
    RETURNED = "RETURNED"
    OVERDUE = "OVERDUE"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"


class WarrantyClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


class FailureMode(str, Enum):
    WINDING_SHORT = "WINDING_SHORT"
    GROUND_FAULT = "GROUND_FAULT"
    BEARING_FAILURE = "BEARING_FAILURE"
    OVERLOAD = "OVERLOAD"
    INGRESS = "INGRESS"
    MISAPPLICATION = "MISAPPLICATION"
    UNAUTHORIZED_REPAIR = "UNAUTHORIZED_REPAIR"


class Remedy(str, Enum):
    FREE_REWIND = "FREE_REWIND"
    PRORATED_CREDIT = "PRORATED_CREDIT"


class Shop(TypedDict, total=False):
    id: str
    shop_name: str
    easa_accreditation_id: str
    labor_rate_small_cents: int
    labor_rate_medium_cents: int
    labor_rate_large_cents: int
    labor_rate_xlarge_cents: int
    rush_premium_pct: float
    replace_threshold_pct: float
    supplies_low_pct: float
    supplies_high_pct: float
    warranty_months: int
    pool_slot_monthly_cents: int
    pool_loan_daily_cents: int
    pool_loan_grace_days: int
    currency: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    shop_id: str
    company_name: str
    account_credit_cents: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class Motor(TypedDict, total=False):
    id: str
    shop_id: str
    owner_customer_id: Optional[str]
    serial_number: str
    rated_kw: float
    frame_mm: int
    voltage_v: int
    manufacture_year: int
    custody: str
    is_pool_spare: bool
    supersedes_motor_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    shop_id: str
    customer_id: str
    motor_id: str
    priority: str
    no_charge: bool
    status: str
    failure_diagnosis: Optional[str]
    rewind_hours: Optional[int]
    materials_cents: Optional[int]
    replacement_cost_cents: Optional[int]
    active_quote_id: Optional[str]
    invoice_total_cents: int
    delivered_at: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestRecord(TypedDict, total=False):
    # Append-only record: carries only id + created_at from the common set (PRD §2.5).
    id: str
    work_order_id: str
    kind: str
    measured_watts: Optional[int]
    vibration_mm_s: Optional[float]
    insulation_megohms: Optional[int]
    verdict: str
    recorded_by: str
    notes: Optional[str]
    created_at: str


class Quote(TypedDict, total=False):
    id: str
    work_order_id: str
    variant: str
    rewind_labor_cents: int
    rewind_materials_cents: int
    shop_supplies_cents: int
    rush_premium_cents: int
    rewind_total_cents: int
    risk_pct: float
    risk_cost_cents: int
    tco_total_cents: int
    recommendation: str
    status: str
    issued_at: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoilDataRecord(TypedDict, total=False):
    # Append-only record: carries only id + created_at from the common set (PRD §2.5).
    id: str
    work_order_id: str
    wire_gauge_awg: str
    turns_per_coil: int
    coils_per_phase: int
    connection: str
    winding_resistance_ohms: float
    easa_form_version: str
    recorded_by: str
    created_at: str


class SparePoolContract(TypedDict, total=False):
    id: str
    shop_id: str
    customer_id: str
    slot_count: int
    activated_on: str
    status: str
    first_month_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class PoolLoan(TypedDict, total=False):
    id: str
    contract_id: str
    work_order_id: str
    spare_motor_id: str
    checked_out_at: str
    due_at: Optional[str]
    returned_at: Optional[str]
    overdue_days: int
    overdue_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    work_order_id: str
    customer_id: str
    total_cents: int
    amount_paid_cents: int
    balance_due_cents: int
    issued_at: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict, total=False):
    id: str
    work_order_id: str
    customer_id: str
    failure_mode: str
    filed_at: str
    months_elapsed: int
    remedy: Optional[str]
    credit_cents: int
    status: str
    reviewed_by: Optional[str]
    resolution_work_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
