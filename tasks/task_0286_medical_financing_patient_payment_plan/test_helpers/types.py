"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the common lifecycle fields id, created_at, updated_at, and
version (PRD §2.4), so every TypedDict below lists all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Role enum ────────────────────────────────────────────────────────────
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROVIDER = "Provider"
    PATIENT = "Patient"
    ANONYMOUS = "Anonymous"


# ─── Status enums ─────────────────────────────────────────────────────────
class ProviderStatus(str, Enum):
    PENDING = "PENDING"
    ENROLLED = "ENROLLED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PromotionalPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ProviderPromotionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    WITHDRAWN = "WITHDRAWN"


class CreditApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class PatientAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    CLOSED = "CLOSED"


class AutopayEnrollmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    REVOKED = "REVOKED"


class SettlementAxis(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"
    VOID = "VOID"


class PromoAxis(str, Enum):
    DEFERRED = "DEFERRED"
    PAID_IN_FULL = "PAID_IN_FULL"
    INTEREST_FORFEITED = "INTEREST_FORFEITED"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"


class PaymentStatus(str, Enum):
    POSTED = "POSTED"
    REVERSED = "REVERSED"


class PaymentType(str, Enum):
    AUTOPAY = "AUTOPAY"
    MANUAL = "MANUAL"
    PAYOFF = "PAYOFF"


class BillingStatementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RefundKind(str, Enum):
    VOID = "VOID"
    REFUND = "REFUND"


class RefundStatus(str, Enum):
    APPLIED = "APPLIED"


class Specialty(str, Enum):
    DENTAL = "DENTAL"
    VISION = "VISION"
    VETERINARY = "VETERINARY"
    DERMATOLOGY = "DERMATOLOGY"
    GENERAL = "GENERAL"


class PlanCategory(str, Enum):
    DEFERRED_INTEREST = "DEFERRED_INTEREST"
    EQUAL_PAYMENT = "EQUAL_PAYMENT"
    REDUCED_APR = "REDUCED_APR"


# ─── Entity TypedDicts (all carry id + created_at + updated_at + version) ──
class Provider(TypedDict):
    id: str
    legal_name: str
    specialty: str
    tax_id: str
    base_merchant_discount_rate: float
    status: str
    monthly_settled_volume_cents: int
    settled_net_cents: int
    created_at: str
    updated_at: str
    version: int


class PromotionalPlan(TypedDict):
    id: str
    name: str
    plan_category: str
    deferred_period_months: int
    promo_apr: float
    min_payment_factor: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProviderPromotion(TypedDict):
    id: str
    provider_id: str
    promotional_plan_id: str
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditApplication(TypedDict):
    id: str
    applicant_full_name: str
    applicant_ssn_last4: str
    stated_annual_income_cents: int
    requested_limit_cents: int
    provisional_limit_cents: int
    approved_limit_cents: Optional[int]
    status: str
    patient_account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PatientAccount(TypedDict):
    id: str
    credit_application_id: str
    account_holder_name: str
    credit_limit_cents: int
    current_balance_cents: int
    available_credit_cents: int
    delinquency_strikes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AutopayEnrollment(TypedDict):
    id: str
    patient_account_id: str
    funding_token: str
    draft_day_of_month: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinancedPurchase(TypedDict):
    id: str
    provider_id: str
    patient_account_id: str
    provider_promotion_id: str
    principal_cents: int
    promo_start: str
    promo_end: str
    principal_paid_cents: int
    deferred_interest_posted_cents: int
    settlement_status: str
    promo_status: str
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict):
    id: str
    financed_purchase_id: str
    provider_id: str
    gross_cents: int
    discount_rate_applied: float
    discount_fee_cents: int
    net_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict):
    id: str
    patient_account_id: str
    amount_cents: int
    payment_type: str
    posted_at: str
    allocation: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingStatement(TypedDict):
    id: str
    patient_account_id: str
    period_start: str
    period_end: str
    opening_balance_cents: int
    minimum_payment_due_cents: int
    amount_paid_in_cycle_cents: int
    min_payment_satisfied: bool
    due_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    financed_purchase_id: str
    refund_kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
