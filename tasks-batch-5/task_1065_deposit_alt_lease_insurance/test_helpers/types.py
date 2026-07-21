"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class PropertyProgramStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class PropertyType(str, Enum):
    SINGLE_FAMILY = "SINGLE_FAMILY"
    MULTI_FAMILY = "MULTI_FAMILY"
    CONDO = "CONDO"


class RenterEnrollmentStatus(str, Enum):
    PENDING_UNDERWRITING = "PENDING_UNDERWRITING"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class PaymentPlan(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL_UPFRONT = "ANNUAL_UPFRONT"


class RiskTier(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PolicyStatus(str, Enum):
    AWAITING_FIRST_PAYMENT = "AWAITING_FIRST_PAYMENT"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class PremiumInvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"


class ClaimType(str, Enum):
    UNPAID_RENT = "UNPAID_RENT"
    PROPERTY_DAMAGE = "PROPERTY_DAMAGE"
    BOTH = "BOTH"


class ClaimStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    NEEDS_INFO = "NEEDS_INFO"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CLOSED = "CLOSED"


class PayoutStatus(str, Enum):
    PENDING = "PENDING"
    DISBURSED = "DISBURSED"
    REVERSED = "REVERSED"


class SubrogationCaseStatus(str, Enum):
    OPEN = "OPEN"
    DEMAND_SENT = "DEMAND_SENT"
    PAID_IN_FULL = "PAID_IN_FULL"
    WRITTEN_OFF = "WRITTEN_OFF"


class RecoveryPaymentStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    REVERSED = "REVERSED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    LANDLORD = "Landlord"
    RENTER = "Renter"
    UNDERWRITING_AGENT = "UnderwritingAgent"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


# ─── Entities with common_fields: true (id, created_at, updated_at, version) ───

class Landlord(TypedDict):
    id: str
    full_name: str
    email: str
    phone_number: str
    created_at: str
    updated_at: str
    version: int


class Property(TypedDict):
    id: str
    landlord_id: str
    address_line1: str
    city: str
    state_code: str
    monthly_rent_cents: int
    property_type: str
    program_status: str
    terminated_at: Optional[str]
    total_paid_claims_cents: int
    created_at: str
    updated_at: str
    version: int


class Renter(TypedDict):
    id: str
    full_name: str
    email: str
    phone_number: str
    created_at: str
    updated_at: str
    version: int


class RenterEnrollment(TypedDict):
    id: str
    property_id: str
    renter_id: str
    payment_plan: str
    requested_coverage_limit_cents: int
    self_reported_annual_income_cents: int
    verified_annual_income_cents: Optional[int]
    employment_verified: bool
    credit_proxy_score: int
    prior_eviction_count: int
    lease_start_date: str
    lease_end_date: str
    risk_score_self_reported: Optional[float]
    risk_score_verified: Optional[float]
    risk_tier: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict):
    id: str
    renter_enrollment_id: str
    coverage_limit_cents: int
    payment_plan: str
    monthly_fee_cents: int
    gross_available_coverage_cents: int
    net_available_coverage_cents: int
    lease_start_date: str
    lease_end_date: str
    status: str
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PremiumInvoice(TypedDict):
    id: str
    policy_id: str
    billing_period_start: str
    billing_period_end: str
    amount_cents: int
    insurance_premium_cents: int
    platform_fee_cents: int
    state_tax_cents: int
    due_date: str
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict):
    id: str
    policy_id: str
    claim_type: str
    line_items: List[dict]
    total_claimed_amount_cents: int
    approved_amount_cents: Optional[int]
    deductible_cents: Optional[int]
    status: str
    reviewing_adjuster_id: Optional[str]
    decision_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payout(TypedDict):
    id: str
    claim_id: str
    amount_cents: int
    status: str
    disbursing_adjuster_id: Optional[str]
    disbursed_at: Optional[str]
    reversed_at: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubrogationCase(TypedDict):
    id: str
    claim_id: str
    original_demand_amount_cents: int
    outstanding_balance_cents: int
    status: str
    demand_sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecoveryPayment(TypedDict):
    id: str
    subrogation_case_id: str
    amount_cents: int
    status: str
    paid_at: str
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── common_fields: false — append-only/static config, ONLY id + created_at ───

class StateComplianceRule(TypedDict):
    id: str
    state_code: str
    enrollment_allowed: bool
    max_monthly_fee_pct_of_rent: float
    cooling_off_buffer_days: int
    mandatory_alternative_offering: bool
    created_at: str
