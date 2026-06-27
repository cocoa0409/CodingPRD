"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and state vocabularies described in the Credit-Builder Loan PRD.
"""
from enum import Enum
from typing import TypedDict, List


# --- Roles -----------------------------------------------------------------

class UserRole(str, Enum):
    BORROWER = "Borrower"
    LOAN_SERVICER = "LoanServicer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Status enums ----------------------------------------------------------

class AccountStatus(str, Enum):
    OPEN = "OPEN"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class KycStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class DisclosureStatusOnAccount(str, Enum):
    UNACKNOWLEDGED = "UNACKNOWLEDGED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class AccountPosture(str, Enum):
    BLOCKED = "BLOCKED"
    ELIGIBLE = "ELIGIBLE"
    FROZEN = "FROZEN"


class ProductKind(str, Enum):
    LOAN = "LOAN"
    SECURED_CARD = "SECURED_CARD"


class DisclosureStatus(str, Enum):
    ISSUED = "ISSUED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    SUPERSEDED = "SUPERSEDED"


class LoanLifecycleStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PAID_OFF = "PAID_OFF"
    GRADUATED = "GRADUATED"
    DEFAULTED = "DEFAULTED"
    CANCELLED = "CANCELLED"


class LoanDelinquencyStatus(str, Enum):
    CURRENT = "CURRENT"
    DPD_30 = "DPD_30"
    DPD_60 = "DPD_60"
    DPD_90 = "DPD_90"
    CHARGED_OFF = "CHARGED_OFF"


class InstallmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID = "PAID"
    LATE = "LATE"


class PaymentSource(str, Enum):
    MANUAL = "MANUAL"
    AUTOPAY = "AUTOPAY"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"


class SecuredCardStatus(str, Enum):
    PENDING = "PENDING"
    FUNDED = "FUNDED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class CardDepositStatus(str, Enum):
    POSTED = "POSTED"
    RELEASED = "RELEASED"


class AutopayStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class TradelineKind(str, Enum):
    LOAN = "LOAN"
    SECURED_CARD = "SECURED_CARD"


class PaymentRating(str, Enum):
    ON_TIME = "ON_TIME"
    LATE_30 = "LATE_30"
    LATE_60 = "LATE_60"
    LATE_90 = "LATE_90"
    CHARGE_OFF = "CHARGE_OFF"


class PayoffQuoteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


# --- Entity TypedDicts -----------------------------------------------------
# Resources carrying the full common field set: id, created_at, updated_at, version.

class Account(TypedDict):
    id: str
    email: str
    full_name: str
    state_code: str
    kyc_status: str
    disclosure_status: str
    posture: str
    status: str
    wallet_cents: int
    created_at: str
    updated_at: str
    version: int


class Disclosure(TypedDict):
    id: str
    account_id: str
    product_kind: str
    apr_bps: int
    admin_fee_cents: int
    status: str
    signed_by_compliance_user_id: str
    acknowledged_at: str
    created_at: str
    updated_at: str
    version: int


class CreditBuilderLoan(TypedDict):
    id: str
    account_id: str
    disclosure_id: str
    principal_cents: int
    term_months: int
    apr_bps: int
    monthly_payment_cents: int
    funded_at: str
    principal_paid_cents: int
    interest_paid_cents: int
    outstanding_principal_cents: int
    lifecycle_status: str
    delinquency_status: str
    on_time_streak: int
    missed_count: int
    funded_by_servicer_user_id: str
    created_at: str
    updated_at: str
    version: int


class InstallmentSchedule(TypedDict):
    id: str
    loan_id: str
    period_index: int
    due_date: str
    amount_due_cents: int
    principal_component_cents: int
    interest_component_cents: int
    amount_paid_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    loan_id: str
    amount_cents: int
    source: str
    applied_principal_cents: int
    applied_interest_cents: int
    applied_fee_cents: int
    posted_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SecuredCard(TypedDict):
    id: str
    account_id: str
    disclosure_id: str
    deposit_cents: int
    credit_limit_cents: int
    balance_cents: int
    status: str
    graduation_eligible: bool
    created_at: str
    updated_at: str
    version: int


class CardDeposit(TypedDict):
    id: str
    secured_card_id: str
    amount_cents: int
    status: str
    released_at: str
    created_at: str
    updated_at: str
    version: int


class AutopayEnrollment(TypedDict):
    id: str
    loan_id: str
    day_of_month: int
    funding_wallet: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PayoffQuote(TypedDict):
    id: str
    loan_id: str
    quote_as_of: str
    payoff_amount_cents: int
    scheduled_remaining_cents: int
    interest_savings_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only audit records: carry ONLY id + created_at (no updated_at, no version).

class BureauReport(TypedDict):
    id: str
    loan_id: str
    tradeline_kind: str
    cycle_label: str
    payment_rating: str
    reported_balance_cents: int
    bureaus: List[str]
    created_at: str


class ScoreSnapshot(TypedDict):
    id: str
    account_id: str
    cycle_label: str
    simulated_score: int
    score_delta: int
    created_at: str
