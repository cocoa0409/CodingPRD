"""Domain types: entity TypedDicts, status enums, and the role enum.

All field names mirror the Renters Insurance API contract exactly.
Every entity carries the common fields id/created_at/updated_at/version.
"""
from enum import Enum
from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    UNDERWRITER = "Underwriter"
    POLICYHOLDER = "Policyholder"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------
class BundleStatus(str, Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"


class PolicyStatus(str, Enum):
    QUOTED = "QUOTED"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class CoverageType(str, Enum):
    PERSONAL_PROPERTY = "PERSONAL_PROPERTY"
    LIABILITY = "LIABILITY"
    LOSS_OF_USE = "LOSS_OF_USE"


class CoverageLineStatus(str, Enum):
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"
    SUSPENDED = "SUSPENDED"


class ScheduledItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class AdditionalInsuredStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class InterestType(str, Enum):
    LANDLORD = "LANDLORD"
    PROPERTY_MANAGER = "PROPERTY_MANAGER"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


class PaymentStatus(str, Enum):
    CLEARED = "CLEARED"
    VOIDED = "VOIDED"


class PaymentMethod(str, Enum):
    CARD = "CARD"
    ACH = "ACH"
    CHECK = "CHECK"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SETTLED = "SETTLED"
    SUSPENDED = "SUSPENDED"


class ValuationMethod(str, Enum):
    RCV = "RCV"
    ACV = "ACV"


class BillingMode(str, Enum):
    ANNUAL = "ANNUAL"
    MONTHLY = "MONTHLY"


class TerritoryCode(str, Enum):
    HIGH = "HIGH"
    STANDARD = "STANDARD"
    LOW = "LOW"


class RefundMethod(str, Enum):
    PRO_RATA = "PRO_RATA"
    SHORT_RATE = "SHORT_RATE"


# --------------------------------------------------------------------------
# Entity TypedDicts (all carry common fields)
# --------------------------------------------------------------------------
class Policyholder(TypedDict):
    id: str
    email: str
    full_name: str
    mailing_address: str
    created_at: str
    updated_at: str
    version: int


class Bundle(TypedDict):
    id: str
    policyholder_id: str
    name: str
    active_member_count: int
    discount_active: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    policyholder_id: str
    bundle_id: Optional[str]
    insured_address: str
    territory_code: str
    effective_date: str
    expiry_date: str
    deductible_cents: int
    pp_valuation_method: str
    billing_mode: str
    annual_premium_cents: int
    refund_method: Optional[str]
    refund_amount_cents: Optional[int]
    lapse_reason: Optional[str]
    reinstatement_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CoverageLine(TypedDict):
    id: str
    policy_id: str
    coverage_type: str
    limit_cents: int
    settled_cents: int
    remaining_limit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScheduledItem(TypedDict):
    id: str
    policy_id: str
    description: str
    appraised_value_cents: int
    deductible_waived: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AdditionalInsured(TypedDict):
    id: str
    policy_id: str
    party_name: str
    interest_type: str
    notify_email: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PremiumInvoice(TypedDict):
    id: str
    policy_id: str
    amount_cents: int
    due_date: str
    paid_cents: int
    balance_due_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    invoice_id: str
    amount_cents: int
    method: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    loss_type: str
    loss_date: str
    displacement_start: Optional[str]
    displacement_end: Optional[str]
    valuation_method: Optional[str]
    covered_loss_cents: int
    deductible_applied_cents: int
    settlement_cents: int
    denial_reason: Optional[str]
    appeal_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ClaimItem(TypedDict):
    id: str
    claim_id: str
    coverage_line_id: str
    scheduled_item_id: Optional[str]
    replacement_cost_cents: int
    age_months: int
    useful_life_months: int
    covered_item_cents: int
    created_at: str
    updated_at: str
    version: int
