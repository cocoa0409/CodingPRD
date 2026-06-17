"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD entity model and lifecycle definitions. Entities that are
full first-class records carry id/created_at/updated_at/version; the append-only
ledger lines (Curtailment, ServiceLine, PartLine) carry only id + created_at.
"""
from enum import Enum
from typing import TypedDict, Optional


# ─── Role enum ────────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    SALES_MANAGER = "SalesManager"
    FINANCE_MANAGER = "FinanceManager"
    SERVICE_ADVISOR = "ServiceAdvisor"
    PARTS_CLERK = "PartsClerk"
    DEALER_PRINCIPAL = "DealerPrincipal"


# ─── Status enums ─────────────────────────────────────────────────────────────
class UnitStatus(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    IN_STOCK = "IN_STOCK"
    ON_HOLD = "ON_HOLD"
    SOLD = "SOLD"
    DELIVERED = "DELIVERED"


class UnitCategory(str, Enum):
    MOTORCYCLE = "MOTORCYCLE"
    ATV = "ATV"
    UTV = "UTV"
    PWC = "PWC"
    SNOWMOBILE = "SNOWMOBILE"


class AcquisitionKind(str, Enum):
    NEW_FLOORED = "NEW_FLOORED"
    TRADE_IN = "TRADE_IN"
    CASH_OWNED = "CASH_OWNED"


class FloorPlanLoanStatus(str, Enum):
    OPEN = "OPEN"
    CURTAILMENT_DUE = "CURTAILMENT_DUE"
    PAID_OFF = "PAID_OFF"


class CurtailmentReason(str, Enum):
    SCHEDULED = "SCHEDULED"
    SALE_PAYOFF = "SALE_PAYOFF"
    VOLUNTARY = "VOLUNTARY"


class DealStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    FINANCE_SUBMITTED = "FINANCE_SUBMITTED"
    APPROVED = "APPROVED"
    DELIVERED = "DELIVERED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"


class TradeInStatus(str, Enum):
    APPRAISED = "APPRAISED"
    ACCEPTED = "ACCEPTED"
    TITLED = "TITLED"
    REJECTED = "REJECTED"


class RepairOrderWorkStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    WORK_COMPLETE = "WORK_COMPLETE"
    CANCELLED = "CANCELLED"


class RepairOrderBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    VOID = "VOID"


class PartLineStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class StorageAgreementStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class TestRideWaiverStatus(str, Enum):
    SIGNED = "SIGNED"
    RIDE_LOGGED = "RIDE_LOGGED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class WarrantyClaimKind(str, Enum):
    WARRANTY = "WARRANTY"
    RECALL = "RECALL"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"


# ─── Entity TypedDicts (full records: id+created_at+updated_at+version) ────────
class Customer(TypedDict):
    id: str
    full_name: str
    email: str
    phone: str
    created_at: str
    updated_at: str
    version: int


class Unit(TypedDict):
    id: str
    vin: str
    category: str
    model_year: int
    msrp_cents: int
    dealer_cost_cents: int
    acquisition_kind: str
    status: str
    floor_plan_loan_id: Optional[str]
    held_by_deal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FloorPlanLoan(TypedDict):
    id: str
    unit_id: str
    original_advance_cents: int
    principal_outstanding_cents: int
    cumulative_curtailment_cents: int
    accrued_interest_cents: int
    opened_on: str
    apr_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deal(TypedDict):
    id: str
    customer_id: str
    unit_id: str
    trade_in_id: Optional[str]
    sale_price_cents: int
    freight_setup_cents: int
    doc_fee_cents: int
    tax_rate_bps: int
    down_payment_cents: int
    trade_allowance_cents: int
    out_the_door_cents: int
    amount_financed_cents: int
    approved_lender_payoff_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeIn(TypedDict):
    id: str
    customer_id: str
    vin: str
    category: str
    appraised_value_cents: int
    estimated_payoff_cents: int
    status: str
    resulting_unit_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    name: str
    hourly_cost_cents: int
    cleanup_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict):
    id: str
    unit_id: str
    customer_id: str
    technician_id: str
    appointment_start: str
    appointment_end: str
    is_warranty: bool
    authorized_amount_cents: int
    labor_total_cents: int
    parts_total_cents: int
    shop_supplies_cents: int
    ro_total_cents: int
    work_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict):
    id: str
    sku: str
    description: str
    unit_price_cents: int
    on_hand_qty: int
    reserved_qty: int
    consumed_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class StorageBay(TypedDict):
    id: str
    label: str
    created_at: str
    updated_at: str
    version: int


class StorageAgreement(TypedDict):
    id: str
    unit_id: str
    customer_id: str
    storage_bay_id: str
    period_start: str
    period_end: str
    includes_winterization: bool
    monthly_rate_cents: int
    storage_fee_cents: int
    prep_repair_order_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TestRideWaiver(TypedDict):
    id: str
    customer_id: str
    unit_id: str
    signed_at: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    unit_id: str
    repair_order_id: Optional[str]
    kind: str
    claim_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledger lines (only id + created_at) ──────────────────────────
class Curtailment(TypedDict):
    id: str
    floor_plan_loan_id: str
    principal_cents: int
    reason: str
    status: str
    created_at: str


class ServiceLine(TypedDict):
    id: str
    repair_order_id: str
    operation_code: str
    flat_rate_hours: float
    extended_labor_cents: int
    created_at: str


class PartLine(TypedDict):
    id: str
    repair_order_id: str
    part_id: str
    quantity: int
    extended_cents: int
    status: str
    created_at: str
