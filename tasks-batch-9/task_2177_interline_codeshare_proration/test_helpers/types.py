"""Domain types for the Interline & Codeshare Proration API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.  Two record types (ExchangeRate, ProrationRun) are append-only
ledger entries: they carry ``id`` and ``created_at`` only, with no
``updated_at`` and no ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
class UserRole(str, Enum):
    CLEARINGHOUSE_OPERATOR = "ClearinghouseOperator"
    REVENUE_ACCOUNTANT = "RevenueAccountant"
    BILLING_AGENT = "BillingAgent"
    INTERLINE_AUDITOR = "InterlineAuditor"


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #
class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"


class CarrierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgreementType(str, Enum):
    STRAIGHT_RATE = "STRAIGHT_RATE"
    SPA_FLAT = "SPA_FLAT"
    SPA_PERCENT = "SPA_PERCENT"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    OPERATOR_SUSPENDED = "OPERATOR_SUSPENDED"
    CARRIER_SUSPENDED = "CARRIER_SUSPENDED"


class ClassOfService(str, Enum):
    ECONOMY = "ECONOMY"
    PREMIUM = "PREMIUM"
    BUSINESS = "BUSINESS"
    FIRST = "FIRST"


class PeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class ProrationStatus(str, Enum):
    UNPRORATED = "UNPRORATED"
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    REPRORATION_REQUIRED = "REPRORATION_REQUIRED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    BILLED = "BILLED"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class CouponStatus(str, Enum):
    OPEN = "OPEN"
    FLOWN = "FLOWN"
    VOID = "VOID"
    ADJUSTED = "ADJUSTED"


class AllocationBasis(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    STRAIGHT_RATE = "STRAIGHT_RATE"
    SPA_FLAT = "SPA_FLAT"
    SPA_PERCENT = "SPA_PERCENT"


class FfpTier(str, Enum):
    NONE = "NONE"
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class RunType(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    PARTIALLY_REJECTED = "PARTIALLY_REJECTED"
    FULLY_REJECTED = "FULLY_REJECTED"
    SETTLED = "SETTLED"


class MemoStatus(str, Enum):
    RAISED = "RAISED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    WITHDRAWN = "WITHDRAWN"
    ARBITRATION = "ARBITRATION"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_DENIED = "RESOLVED_DENIED"


class MemoReasonCode(str, Enum):
    PRORATE_FACTOR_DISPUTE = "PRORATE_FACTOR_DISPUTE"
    SPA_NOT_APPLIED = "SPA_NOT_APPLIED"
    FARE_BASIS_ERROR = "FARE_BASIS_ERROR"
    DUPLICATE_BILLING = "DUPLICATE_BILLING"
    CURRENCY_ERROR = "CURRENCY_ERROR"


class AgingBucket(str, Enum):
    CURRENT = "CURRENT"
    AGED_30 = "AGED_30"
    AGED_60 = "AGED_60"
    AGED_90 = "AGED_90"


class ArbitrationRuling(str, Enum):
    UPHELD = "UPHELD"
    DENIED = "DENIED"


class SampleStatus(str, Enum):
    DRAWN = "DRAWN"
    IN_REVIEW = "IN_REVIEW"
    CLOSED_IMMATERIAL = "CLOSED_IMMATERIAL"
    CLAIM_RAISED = "CLAIM_RAISED"
    CLAIM_ACCEPTED = "CLAIM_ACCEPTED"
    CLAIM_DENIED = "CLAIM_DENIED"


class ClaimDecision(str, Enum):
    ACCEPT = "ACCEPT"
    DENY = "DENY"


# --------------------------------------------------------------------------- #
# Entities carrying id + created_at + updated_at + version
# --------------------------------------------------------------------------- #
class Carrier(TypedDict):
    id: str
    iata_code: str
    name: str
    base_currency: str
    credit_limit_minor: int
    status: str
    pending_receivable_minor: int
    pending_payable_minor: int
    settled_receivable_minor: int
    settled_payable_minor: int
    net_position_minor: int
    period_accrued_miles: int
    period_ffp_cost_estimate_minor: int
    period_ffp_cost_trued_up_minor: int
    ffp_true_up_delta_minor: int
    open_reproration_count: int
    audit_flag: bool
    created_at: str
    updated_at: str
    version: int


class ProrateAgreement(TypedDict):
    id: str
    issuing_carrier_id: str
    partner_carrier_id: str
    agreement_type: str
    settlement_currency: str
    effective_from: str
    effective_to: str
    status: str
    suspension_reason: str
    factor_count: int
    created_at: str
    updated_at: str
    version: int


class ProrateFactor(TypedDict):
    id: str
    agreement_id: str
    origin: str
    destination: str
    class_of_service: str
    factor_bp: Optional[int]
    flat_amount_minor: Optional[int]
    percent_bp: Optional[int]
    specificity_score: int
    created_at: str
    updated_at: str
    version: int


class SettlementPeriod(TypedDict):
    id: str
    period_code: str
    period_start: str
    period_end: str
    submission_deadline: str
    rate_fixing_date: str
    settlement_currency: str
    status: str
    cleared_invoice_count: int
    closed_at: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict):
    id: str
    ticket_number: str
    validating_carrier_id: str
    sale_currency: str
    total_fare_minor: int
    issue_date: str
    proration_status: str
    billing_status: str
    coupon_count: int
    unallocated_residual_minor: int
    last_run_type: str
    created_at: str
    updated_at: str
    version: int


class Coupon(TypedDict):
    id: str
    ticket_id: str
    coupon_number: int
    origin: str
    destination: str
    operating_carrier_id: str
    class_of_service: str
    tpm_miles: int
    coupon_status: str
    flown_at: Optional[str]
    weight_units: int
    allocated_amount_minor: int
    allocation_basis: str
    ffp_miles_awarded: int
    ffp_accrual_cost_minor: int
    ffp_tier: str
    billing_invoice_id: Optional[str]
    adjusted_amount_minor: int
    created_at: str
    updated_at: str
    version: int


class BillingInvoice(TypedDict):
    id: str
    settlement_period_id: str
    billing_carrier_id: str
    billed_carrier_id: str
    billing_currency: str
    status: str
    coupon_count: int
    gross_billed_minor: int
    ich_fee_bp: int
    ich_handling_fee_minor: int
    late_submission_penalty_minor: int
    total_claim_minor: int
    provisional_rate_scaled: int
    provisional_settlement_minor: int
    fixed_rate_scaled: int
    final_settlement_minor: int
    fx_variance_minor: int
    disputed_amount_minor: int
    rejected_amount_minor: int
    net_billed_minor: int
    submitted_at: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RejectionMemo(TypedDict):
    id: str
    invoice_id: str
    coupon_id: str
    raised_by_carrier_id: str
    stage: int
    amount_minor: int
    reason_code: str
    status: str
    counter_amount_minor: int
    counter_reason: Optional[str]
    raised_at: str
    resolved_at: Optional[str]
    age_days: int
    aging_bucket: str
    settlement_impact_minor: int
    created_at: str
    updated_at: str
    version: int


class AuditSample(TypedDict):
    id: str
    auditing_carrier_id: str
    audited_carrier_id: str
    settlement_period_id: str
    claim_currency: str
    sample_coupon_ids: List[str]
    status: str
    population_coupon_count: int
    population_allocated_minor: int
    sampled_coupon_count: int
    sampled_allocated_minor: int
    sampled_undercharge_minor: int
    findings_count: int
    undercharge_ratio_bp: int
    coverage_bp: int
    haircut_bp: int
    extrapolated_gross_minor: int
    claim_amount_minor: int
    claim_settlement_minor: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --------------------------------------------------------------------------- #
# Append-only ledger entries: id + created_at only.
# No updated_at, no version — the PRD says neither field appears on them.
# --------------------------------------------------------------------------- #
class ExchangeRate(TypedDict):
    id: str
    from_currency: str
    to_currency: str
    effective_date: str
    rate_scaled: int
    created_at: str


class ProrationRun(TypedDict):
    id: str
    ticket_id: str
    run_type: str
    pool_minor: int
    spa_total_minor: int
    straight_rate_pool_minor: int
    total_weight_units: int
    included_coupon_count: int
    rounding_residual_minor: int
    allocated_total_minor: int
    unallocated_residual_minor: int
    created_at: str
