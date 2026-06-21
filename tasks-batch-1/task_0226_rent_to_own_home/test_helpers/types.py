"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the Rent-To-Own Home PRD (§2.4, §3). Every primary resource carries
the common system-managed fields id / created_at / updated_at / version (§2.4).
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    LANDLORD = "Landlord"
    TENANT = "Tenant"
    ESCROW_AGENT = "EscrowAgent"


class PropertyStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNDER_AGREEMENT = "UNDER_AGREEMENT"
    SOLD = "SOLD"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXERCISED = "EXERCISED"
    CONVERTED = "CONVERTED"
    DEFAULTED = "DEFAULTED"
    EXPIRED = "EXPIRED"


class RentPaymentStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    LATE = "LATE"
    FORFEITED = "FORFEITED"


class MaintenanceTicketStatus(str, Enum):
    OPEN = "OPEN"
    APPROVED = "APPROVED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class OptionExerciseStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class MortgageStatus(str, Enum):
    ACTIVE = "ACTIVE"


class Landlord(TypedDict):
    id: str
    legal_name: str
    email: str
    payout_account_ref: str
    created_at: str
    updated_at: str
    version: int


class Tenant(TypedDict):
    id: str
    legal_name: str
    email: str
    credit_score: int
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    landlord_id: str
    address: str
    list_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict):
    id: str
    property_id: str
    tenant_id: str
    landlord_id: str
    locked_price_cents: int
    option_fee_cents: int
    option_fee_creditable: bool
    monthly_payment_cents: int
    credit_pct: float
    max_credit_pct: float
    grace_days: int
    maintenance_threshold_cents: int
    lease_start: str
    option_term_months: int
    status: str
    missed_payment_count: int
    gross_credit_accrued_cents: int
    available_credit_cents: int
    option_deadline: str
    created_at: str
    updated_at: str
    version: int


class RentPayment(TypedDict):
    id: str
    agreement_id: str
    period_index: int
    due_date: str
    amount_cents: int
    paid_at: Optional[str]
    rent_portion_cents: int
    credit_portion_cents: int
    late_fee_cents: int
    supersedes_payment_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MaintenanceTicket(TypedDict):
    id: str
    agreement_id: str
    summary: str
    estimated_cost_cents: int
    actual_cost_cents: Optional[int]
    tenant_share_cents: int
    landlord_share_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OptionExercise(TypedDict):
    id: str
    agreement_id: str
    exercised_at: str
    locked_price_snapshot_cents: int
    max_credit_cap_cents: int
    credit_applied_cents: int
    option_fee_credit_cents: int
    net_due_at_closing_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Mortgage(TypedDict):
    id: str
    agreement_id: str
    option_exercise_id: str
    principal_cents: int
    annual_rate_bps: int
    term_months: int
    monthly_installment_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
