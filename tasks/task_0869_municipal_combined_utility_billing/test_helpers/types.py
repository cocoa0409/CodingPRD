"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    BILLING_SPECIALIST = "BillingSpecialist"
    METER_TECH = "MeterTech"
    COLLECTIONS_OFFICER = "CollectionsOfficer"
    ASSISTANCE_CASEWORKER = "AssistanceCaseworker"
    SUPERVISOR = "Supervisor"
    CUSTOMER = "Customer"


class ServiceType(str, Enum):
    WATER = "WATER"
    SEWER = "SEWER"
    ELECTRIC = "ELECTRIC"
    REFUSE = "REFUSE"


class MeterUnit(str, Enum):
    GALLON = "GALLON"
    KWH = "KWH"
    FLAT = "FLAT"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    SHUTOFF = "SHUTOFF"
    FINALED = "FINALED"
    LIEN_TRANSFERRED = "LIEN_TRANSFERRED"


class MeterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class ReadType(str, Enum):
    ACTUAL = "ACTUAL"
    ESTIMATED = "ESTIMATED"


class BillPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIAL = "PARTIAL"
    PAID = "PAID"


class BillCollectionStatus(str, Enum):
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    IN_LIEN = "IN_LIEN"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentMethod(str, Enum):
    CASH = "CASH"
    CARD = "CARD"
    ACH = "ACH"
    CHECK = "CHECK"


class BudgetBillingPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRUED_UP = "TRUED_UP"
    CANCELLED = "CANCELLED"


class DepositStatus(str, Enum):
    HELD = "HELD"
    APPLIED = "APPLIED"
    REFUNDED = "REFUNDED"


class DepositReason(str, Enum):
    NEW_SERVICE = "NEW_SERVICE"
    DELINQUENCY = "DELINQUENCY"
    COMMERCIAL = "COMMERCIAL"


class ArrangementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    SUPERSEDED = "SUPERSEDED"


class AdjustmentType(str, Enum):
    LEAK = "LEAK"
    ESTIMATE_CORRECTION = "ESTIMATE_CORRECTION"
    GOODWILL = "GOODWILL"


class ReliefMethod(str, Enum):
    SEWER_RELIEF = "SEWER_RELIEF"
    TIER_REPRICE = "TIER_REPRICE"


class AdjustmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ShutoffReason(str, Enum):
    DELINQUENCY = "DELINQUENCY"
    ARRANGEMENT_DEFAULT = "ARRANGEMENT_DEFAULT"


class ShutoffOrigin(str, Enum):
    MANUAL = "MANUAL"
    CASCADE = "CASCADE"


class ShutoffStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class LienTransferStatus(str, Enum):
    PENDING = "PENDING"
    CERTIFIED = "CERTIFIED"
    TRANSFERRED = "TRANSFERRED"


class MoratoriumScope(str, Enum):
    SYSTEM = "SYSTEM"
    ACCOUNT = "ACCOUNT"


class MoratoriumReason(str, Enum):
    WEATHER = "WEATHER"
    MEDICAL = "MEDICAL"
    LEGISLATIVE = "LEGISLATIVE"


# --- Entity TypedDicts ---


class RateSchedule(TypedDict, total=False):
    id: str
    service_type: str
    unit: str
    fixed_charge_cents: int
    tiers: List[dict]
    sewer_rate_cents_per_1000: Optional[int]
    sewer_cap_units: Optional[int]
    effective_date: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    account_holder_name: str
    service_address: str
    occupant_type: str
    prior_annual_charges_cents: int
    status: str
    assistance_program: Optional[str]
    assistance_discount_pct: float
    current_balance_cents: int
    delinquent_balance_cents: int
    deposit_on_hand_cents: int
    move_out_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Meter(TypedDict, total=False):
    id: str
    account_id: str
    service_type: str
    estimated_monthly_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only reading, carries ONLY id + created_at
class MeterReading(TypedDict, total=False):
    id: str
    meter_id: str
    read_date: str
    reading_value: int
    read_type: str
    created_at: str


class Bill(TypedDict, total=False):
    id: str
    account_id: str
    period_start: str
    period_end: str
    due_date: str
    budget_billed: bool
    read_basis: str
    line_charges: List[dict]
    pre_discount_total_cents: int
    assistance_credit_cents: int
    actual_charges_cents: int
    total_due_cents: int
    amount_paid_cents: int
    payment_status: str
    collection_status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    payment_date: str
    method: str
    allocation: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetBillingPlan(TypedDict, total=False):
    id: str
    account_id: str
    plan_year: int
    monthly_budget_cents: int
    cumulative_budgeted_cents: int
    cumulative_actual_cents: int
    deferred_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Deposit(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    reason: str
    applied_cents: int
    refunded_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PaymentArrangement(TypedDict, total=False):
    id: str
    account_id: str
    total_arranged_cents: int
    installment_count: int
    installment_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Adjustment(TypedDict, total=False):
    id: str
    bill_id: str
    adjustment_type: str
    relief_method: Optional[str]
    baseline_units: int
    goodwill_amount_cents: int
    credit_cents: int
    requested_by: str
    approved_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShutoffOrder(TypedDict, total=False):
    id: str
    account_id: str
    scheduled_date: str
    reason: str
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LienTransfer(TypedDict, total=False):
    id: str
    account_id: str
    amount_cents: int
    tax_parcel_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MoratoriumWindow(TypedDict, total=False):
    id: str
    account_id: Optional[str]
    scope: str
    start_date: str
    end_date: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int
