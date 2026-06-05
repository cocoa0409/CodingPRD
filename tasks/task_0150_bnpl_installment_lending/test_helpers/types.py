"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources described in the BNPL Installment Lending PRD §3 and the
common-field rules in §2.4. DisclosureAcceptance is the sole immutable record
(no version / no updated_at) per §2.4.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# --------------------------------------------------------------------------
# Roles (§2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SERVICER = "Servicer"
    BORROWER = "Borrower"
    MERCHANT = "Merchant"


# --------------------------------------------------------------------------
# Status enums (§3 workflows)
# --------------------------------------------------------------------------
class MerchantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    COUNTERED = "COUNTERED"
    DECLINED = "DECLINED"
    ACTIVATED = "ACTIVATED"
    WITHDRAWN = "WITHDRAWN"


class DeclineReason(str, Enum):
    INSUFFICIENT_CREDIT = "INSUFFICIENT_CREDIT"
    MERCHANT_SUSPENDED = "MERCHANT_SUSPENDED"
    DOWN_PAYMENT_TOO_LOW = "DOWN_PAYMENT_TOO_LOW"


class PlanType(str, Enum):
    PAY_IN_4 = "PAY_IN_4"
    MONTHLY = "MONTHLY"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class DelinquencyStatus(str, Enum):
    CURRENT = "CURRENT"
    LATE = "LATE"
    DELINQUENT = "DELINQUENT"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    LATE = "LATE"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"
    CANCELLED = "CANCELLED"


class PaymentSource(str, Enum):
    MANUAL = "MANUAL"
    AUTOPAY = "AUTOPAY"


class ReturnStatus(str, Enum):
    POSTED = "POSTED"


class AutopayMandateStatus(str, Enum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class MerchantSettlementStatus(str, Enum):
    PENDING = "PENDING"
    RELEASED = "RELEASED"
    CLAWED_BACK = "CLAWED_BACK"


# --------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true -> id, created_at, updated_at, version
# common_fields: false (DisclosureAcceptance) -> id + created_at only
# --------------------------------------------------------------------------
class Merchant(TypedDict):
    id: str
    display_name: str
    mdr_bps: int
    settlement_hold_days: int
    status: str
    gross_financed_cents: int
    net_settled_cents: int
    created_at: str
    updated_at: str
    version: int


class Borrower(TypedDict):
    id: str
    full_name: str
    email: str
    annual_income_cents: int
    soft_credit_score: int
    eligible_credit_limit_cents: int
    outstanding_principal_cents: int
    available_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    borrower_id: str
    merchant_id: str
    cart_amount_cents: int
    plan_type: str
    term_months: Optional[int]
    requested_down_payment_cents: int
    apr_bps: int
    financed_principal_cents: int
    approved_down_payment_cents: int
    finance_charge_cents: int
    total_of_payments_cents: int
    status: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisclosureAcceptance(TypedDict):
    id: str
    application_id: str
    disclosed_apr_bps: int
    disclosed_finance_charge_cents: int
    disclosed_total_of_payments_cents: int
    disclosed_installment_count: int
    accepted: bool
    created_at: str
    # NOTE: immutable Reg Z artifact — NO updated_at, NO version (PRD §2.4)


class Loan(TypedDict):
    id: str
    application_id: str
    borrower_id: str
    merchant_id: str
    financed_principal_cents: int
    apr_bps: int
    finance_charge_cents: int
    remaining_principal_cents: int
    total_paid_cents: int
    late_fee_accrued_cents: int
    status: str
    delinquency_status: str
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict):
    id: str
    loan_id: str
    sequence_no: int
    due_date: str
    amount_due_cents: int
    principal_portion_cents: int
    amount_paid_cents: int
    late_fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    loan_id: str
    amount_cents: int
    source: str
    allocation: List[dict]
    unapplied_cents: int
    created_at: str
    updated_at: str
    version: int


class Return(TypedDict):
    id: str
    loan_id: str
    merchant_id: str
    return_amount_cents: int
    principal_reduction_cents: int
    settlement_clawback_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AutopayMandate(TypedDict):
    id: str
    loan_id: str
    borrower_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MerchantSettlement(TypedDict):
    id: str
    merchant_id: str
    loan_id: str
    gross_financed_cents: int
    mdr_fee_cents: int
    net_settlement_cents: int
    clawed_back_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
