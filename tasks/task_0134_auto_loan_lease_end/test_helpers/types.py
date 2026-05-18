"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4 declares two common-fields shapes:

- Persisted entities carrying id + created_at + updated_at + version:
  Customer, Vehicle, LoanContract, LeaseContract, GapInsuranceRider,
  LeaseEndAssessment.
- Immutable / append-only event records carrying ONLY id + created_at:
  Payment, DelinquencyEvent, ClockEvent.

PRD §2.4: "For Payment, state transitions update the row's status
field and the relevant denormalized counters in place, but neither
updated_at nor version exist on the row. DelinquencyEvent and
ClockEvent rows are append-only and never mutated."
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles — PRD §2.1
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LOAN_OFFICER = "LoanOfficer"
    FINANCE_MANAGER = "FinanceManager"
    COLLECTIONS_AGENT = "CollectionsAgent"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Status enums — PRD §3
# ---------------------------------------------------------------------------
class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FicoTier(str, Enum):
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"
    TIER_5_DECLINED = "TIER_5_DECLINED"


class VehicleStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    LEASED = "LEASED"


class LoanContractStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"
    CHARGED_OFF = "CHARGED_OFF"


class LeaseContractStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    MATURED = "MATURED"
    PURCHASED = "PURCHASED"
    RENEWED = "RENEWED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    DEFAULTED = "DEFAULTED"


class LeaseEndElection(str, Enum):
    PURCHASE = "PURCHASE"
    RENEW = "RENEW"
    RETURN = "RETURN"


class PaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    LATE = "LATE"
    DEFAULTED = "DEFAULTED"


class PaymentContractType(str, Enum):
    LOAN = "LOAN"
    LEASE = "LEASE"


class GapRiderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    CLAIMED = "CLAIMED"


class GapRiderContractType(str, Enum):
    LOAN = "LOAN"
    LEASE = "LEASE"


class LeaseEndAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true (id+created_at+updated_at+version)
# ---------------------------------------------------------------------------
class Customer(TypedDict, total=False):
    id: str
    full_name: str
    fico_score: int
    fico_tier: str
    default_count: int
    default_rate: float
    lifetime_payment_count: int
    status: str
    clock_day_index: int
    created_at: str
    updated_at: str
    version: int


class Vehicle(TypedDict, total=False):
    id: str
    vin: str
    model: str
    msrp_cents: int
    residual_factor_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LoanContract(TypedDict, total=False):
    id: str
    customer_id: str
    vehicle_id: str
    principal_cents: int
    down_payment_cents: int
    term_months: int
    apr_bps: int
    base_apr_bps: int
    monthly_payment_cents: int
    remaining_principal_cents: int
    total_principal_paid_cents: int
    total_interest_paid_cents: int
    payments_made_count: int
    payments_scheduled_count: int
    status: str
    origination_day_index: int
    created_at: str
    updated_at: str
    version: int


class LeaseContract(TypedDict, total=False):
    id: str
    customer_id: str
    vehicle_id: str
    capitalized_cost_cents: int
    down_payment_cents: int
    term_months: int
    mileage_allowance: int
    money_factor_micro: int
    residual_value_cents: int
    monthly_payment_cents: int
    payments_made_count: int
    payments_scheduled_count: int
    status: str
    lease_end_election: Optional[str]
    origination_day_index: int
    maturity_day_index: int
    created_at: str
    updated_at: str
    version: int


class GapInsuranceRider(TypedDict, total=False):
    id: str
    contract_id: str
    contract_type: str
    monthly_premium_cents: int
    status: str
    claim_payout_cents: int
    attached_day_index: int
    created_at: str
    updated_at: str
    version: int


class LeaseEndAssessment(TypedDict, total=False):
    id: str
    lease_contract_id: str
    odometer_reading: Optional[int]
    mileage_overage: int
    mileage_penalty_cents: int
    disposition_fee_cents: int
    purchase_option_cents: int
    total_due_cents: int
    status: str
    settled_day_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only / immutable records — common_fields: false (id+created_at only)
# PRD §2.4: "Two entities are treated as immutable event records and carry
# only id and created_at: Payment and DelinquencyEvent, plus the read-only
# ClockEvent audit row."
# ---------------------------------------------------------------------------
class Payment(TypedDict, total=False):
    id: str
    created_at: str
    customer_id: str
    contract_id: str
    contract_type: str
    period_index: int
    due_day_index: int
    amount_due_cents: int
    principal_portion_cents: int
    interest_portion_cents: int
    status: str
    paid_day_index: Optional[int]


class DelinquencyEvent(TypedDict, total=False):
    id: str
    created_at: str
    customer_id: str
    payment_id: str
    default_count_after: int
    apr_uplift_bps_applied: int
    affected_contract_ids: List[str]


class ClockEvent(TypedDict, total=False):
    id: str
    created_at: str
    customer_id: str
    days_advanced: int
    new_clock_day_index: int
    payments_due_now: int
    payments_defaulted_now: int


__all__ = [
    # Roles
    "UserRole",
    # Status enums
    "CustomerStatus",
    "FicoTier",
    "VehicleStatus",
    "LoanContractStatus",
    "LeaseContractStatus",
    "LeaseEndElection",
    "PaymentStatus",
    "PaymentContractType",
    "GapRiderStatus",
    "GapRiderContractType",
    "LeaseEndAssessmentStatus",
    # Entities (common_fields=true)
    "Customer",
    "Vehicle",
    "LoanContract",
    "LeaseContract",
    "GapInsuranceRider",
    "LeaseEndAssessment",
    # Immutable / append-only (common_fields=false)
    "Payment",
    "DelinquencyEvent",
    "ClockEvent",
]
