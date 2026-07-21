"""Domain types for the Developer Marketplace Payouts API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import TypedDict, List, Optional


class UserRole(str, Enum):
    DEVELOPER = "Developer"
    REVIEW_AGENT = "ReviewAgent"
    POLICY_OFFICER = "PolicyOfficer"
    FINANCE_OPS = "FinanceOps"
    PLATFORM_ADMIN = "PlatformAdmin"
    STOREFRONT_SERVICE = "StorefrontService"


class DeveloperStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RiskVariant(str, Enum):
    STANDARD = "STANDARD"
    ACCELERATED = "ACCELERATED"


class AppStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class AppCategory(str, Enum):
    PRODUCTIVITY = "PRODUCTIVITY"
    GAMES = "GAMES"
    FINANCE = "FINANCE"
    HEALTH = "HEALTH"
    DEVELOPER_TOOLS = "DEVELOPER_TOOLS"


class ReviewSubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_TRIAGE = "IN_TRIAGE"
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class PricingPlanKind(str, Enum):
    ONE_TIME = "ONE_TIME"
    SUBSCRIPTION = "SUBSCRIPTION"
    IAP = "IAP"


class PricingPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    VOIDED = "VOIDED"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    CHARGED_BACK = "CHARGED_BACK"


class SettlementStatus(str, Enum):
    UNSETTLED = "UNSETTLED"
    ACCRUED = "ACCRUED"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"


class TaxRemitter(str, Enum):
    MARKETPLACE = "MARKETPLACE"
    DEVELOPER = "DEVELOPER"


class RefundStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTED = "EXECUTED"


class RefundReason(str, Enum):
    BUYER_REQUEST = "BUYER_REQUEST"
    FRAUD = "FRAUD"
    POLICY = "POLICY"
    DUPLICATE = "DUPLICATE"


class ChargebackStatus(str, Enum):
    RECEIVED = "RECEIVED"
    REPRESENTED = "REPRESENTED"
    WON = "WON"
    LOST = "LOST"
    REVERSED = "REVERSED"


class PolicyCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    APPEALED = "APPEALED"
    REINSTATED = "REINSTATED"


class PolicyCaseCategory(str, Enum):
    FRAUD = "FRAUD"
    IP_INFRINGEMENT = "IP_INFRINGEMENT"
    MALWARE = "MALWARE"
    CONTENT = "CONTENT"
    PAYMENT_ABUSE = "PAYMENT_ABUSE"


class PolicyCaseSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class PayoutBatchStatus(str, Enum):
    OPEN = "OPEN"
    CALCULATED = "CALCULATED"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PAID = "PAID"
    FAILED = "FAILED"


class PayoutLineStatus(str, Enum):
    PAYABLE = "PAYABLE"
    HELD_BELOW_MINIMUM = "HELD_BELOW_MINIMUM"
    HELD_DEVELOPER = "HELD_DEVELOPER"
    PAID = "PAID"
    FAILED = "FAILED"


class LedgerEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    TAX_PASSTHROUGH = "TAX_PASSTHROUGH"
    TIER_TRUEUP = "TIER_TRUEUP"
    REFUND_REVERSAL = "REFUND_REVERSAL"
    CLAWBACK = "CLAWBACK"
    CLAWBACK_REVERSAL = "CLAWBACK_REVERSAL"
    RESERVE = "RESERVE"
    RECOVERY = "RECOVERY"
    WITHHOLDING = "WITHHOLDING"
    PAYOUT = "PAYOUT"
    CARRYOVER = "CARRYOVER"


class TaxFormStatus(str, Enum):
    ISSUABLE = "ISSUABLE"
    NOT_REQUIRED = "NOT_REQUIRED"


# --- Entity shapes -------------------------------------------------------
# Resources carrying id + created_at + updated_at + version.

class Developer(TypedDict):
    id: str
    legal_name: str
    email: str
    country_code: str
    tax_id_provided: bool
    status: str
    payout_hold: bool
    risk_watch: bool
    policy_strike_count: int
    lifetime_revenue_base_cents: int
    unpaid_accrual_cents: int
    negative_balance_cents: int
    carryover_cents: int
    risk_score: int
    risk_variant: str
    created_at: str
    updated_at: str
    version: int


class App(TypedDict):
    id: str
    developer_id: str
    name: str
    category: str
    listed_countries: List[str]
    status: str
    review_round: int
    policy_strike_count: int
    created_at: str
    updated_at: str
    version: int


class ReviewSubmission(TypedDict):
    id: str
    app_id: str
    round_number: int
    submitted_notes: str
    status: str
    triaged_by_user_id: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PricingPlan(TypedDict):
    id: str
    app_id: str
    kind: str
    price_cents: int
    currency: str
    country_code: str
    billing_period_months: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict):
    id: str
    app_id: str
    pricing_plan_id: str
    developer_id: str
    tax_jurisdiction_id: str
    buyer_country_code: str
    external_order_ref: str
    line_items: List[dict]
    gross_cents: int
    tax_cents: int
    revenue_base_cents: int
    developer_tax_remittance_cents: int
    tax_remitter: str
    provisional_share_bps: int
    provisional_developer_net_cents: int
    platform_fee_cents: int
    refunded_gross_cents: int
    payment_status: str
    settlement_status: str
    captured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Refund(TypedDict):
    id: str
    purchase_id: str
    amount_cents: int
    reason: str
    status: str
    decided_by_user_id: Optional[str]
    developer_net_reversal_cents: int
    tax_reversal_cents: int
    created_at: str
    updated_at: str
    version: int


class Chargeback(TypedDict):
    id: str
    purchase_id: str
    network_case_ref: str
    amount_cents: int
    status: str
    received_at: str
    clawback_cents: int
    created_at: str
    updated_at: str
    version: int


class PolicyCase(TypedDict):
    id: str
    app_id: str
    developer_id: str
    category: str
    severity: str
    status: str
    opened_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoutBatch(TypedDict):
    id: str
    payout_currency: str
    period_start: str
    period_end: str
    status: str
    line_count: int
    total_payable_cents: int
    total_withholding_cents: int
    total_reserve_cents: int
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoutLine(TypedDict):
    id: str
    payout_batch_id: str
    developer_id: str
    gross_earnings_cents: int
    final_share_bps: int
    tier_trueup_cents: int
    reserve_cents: int
    recovery_cents: int
    withholding_cents: int
    payout_amount_cents: int
    carryover_added_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TaxForm1099(TypedDict):
    id: str
    developer_id: str
    tax_year: int
    reportable_cents: int
    withheld_cents: int
    threshold_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only / immutable reference resources: id + created_at ONLY.

class TaxJurisdiction(TypedDict):
    id: str
    country_code: str
    vat_rate_bps: int
    marketplace_facilitator: bool
    created_at: str


class RevenueShareTier(TypedDict):
    id: str
    label: str
    min_cumulative_base_cents: int
    developer_share_bps: int
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    developer_id: str
    purchase_id: Optional[str]
    payout_line_id: Optional[str]
    entry_type: str
    amount_cents: int
    settled: bool
    memo: str
    created_at: str
