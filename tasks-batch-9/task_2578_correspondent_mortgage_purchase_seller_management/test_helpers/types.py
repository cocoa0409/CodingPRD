"""Typed shapes for the thirteen correspondent-lending resources.

All thirteen resource types carry `id`, `created_at`, `updated_at` and
`version`, so every TypedDict below extends `CommonFields`.
"""

from typing import Any, Optional, TypedDict

# ─── Roles ──────────────────────────────────────────────────────────────────


class UserRole:
    SELLER_USER = "SellerUser"
    COUNTERPARTY_ANALYST = "CounterpartyAnalyst"
    QC_REVIEWER = "QCReviewer"
    LOCK_DESK_TRADER = "LockDeskTrader"
    PURCHASE_REVIEWER = "PurchaseReviewer"
    PLATFORM_ADMIN = "PlatformAdmin"

    ALL = (
        SELLER_USER,
        COUNTERPARTY_ANALYST,
        QC_REVIEWER,
        LOCK_DESK_TRADER,
        PURCHASE_REVIEWER,
        PLATFORM_ADMIN,
    )


# ─── Enumerations ───────────────────────────────────────────────────────────


class SellerApprovalStatus:
    APPLIED = "APPLIED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class DeliveryStanding:
    NOT_ELIGIBLE = "NOT_ELIGIBLE"
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SellerType:
    BANK = "BANK"
    CREDIT_UNION = "CREDIT_UNION"
    NON_BANK_IMB = "NON_BANK_IMB"


class ApprovalTier:
    STANDARD = "STANDARD"
    CONDITIONAL = "CONDITIONAL"


class SuspensionReason:
    MANUAL_COUNTERPARTY_ACTION = "MANUAL_COUNTERPARTY_ACTION"
    SCORECARD_DEFECT_RATE = "SCORECARD_DEFECT_RATE"


class StandingAction:
    PLACE_ON_WATCH = "PLACE_ON_WATCH"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    TERMINATE = "TERMINATE"


class FinancialStatementStatus:
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class StatementReviewDecision:
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class QCReviewStatus:
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"


class QCReviewType:
    PRE_APPROVAL = "PRE_APPROVAL"
    ANNUAL_RECERT = "ANNUAL_RECERT"


class QCReviewOutcome:
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class ApprovalDecision:
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


class ProductStatus:
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AdjustmentStatus:
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class CommitmentType:
    MANDATORY = "MANDATORY"
    BEST_EFFORTS = "BEST_EFFORTS"


class CommitmentStatus:
    LOCKED = "LOCKED"
    PARTIALLY_FULFILLED = "PARTIALLY_FULFILLED"
    FULFILLED = "FULFILLED"
    PAIRED_OFF = "PAIRED_OFF"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class PairOffMethod:
    MANDATORY_MARK_TO_MARKET = "MANDATORY_MARK_TO_MARKET"
    BEST_EFFORTS_ADMIN_ONLY = "BEST_EFFORTS_ADMIN_ONLY"
    ADMINISTRATIVE_FLAT = "ADMINISTRATIVE_FLAT"


class Occupancy:
    PRIMARY = "PRIMARY"
    SECOND_HOME = "SECOND_HOME"
    INVESTMENT = "INVESTMENT"


class ServicingElection:
    RETAINED = "RETAINED"
    RELEASED = "RELEASED"


class LoanPurchaseStatus:
    DELIVERED = "DELIVERED"
    IN_REVIEW = "IN_REVIEW"
    SUSPENDED = "SUSPENDED"
    CLEARED_FOR_PURCHASE = "CLEARED_FOR_PURCHASE"
    PURCHASED = "PURCHASED"
    REJECTED = "REJECTED"
    REPURCHASE_DEMANDED = "REPURCHASE_DEMANDED"
    REPURCHASED = "REPURCHASED"


class FirstPaymentStatus:
    PENDING = "PENDING"
    PAID = "PAID"
    MISSED = "MISSED"


class PaymentEventType:
    FIRST_PAYMENT_PAID = "FIRST_PAYMENT_PAID"
    FIRST_PAYMENT_MISSED = "FIRST_PAYMENT_MISSED"


class DefectCategory:
    CREDIT = "CREDIT"
    INCOME = "INCOME"
    COLLATERAL = "COLLATERAL"
    COMPLIANCE = "COMPLIANCE"
    DOCUMENTATION = "DOCUMENTATION"


class DefectSeverity:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class DefectClassification:
    CURABLE = "CURABLE"
    NON_CURABLE = "NON_CURABLE"


class DefectStatus:
    OPEN = "OPEN"
    CURED = "CURED"
    WAIVED = "WAIVED"
    EXPIRED = "EXPIRED"


class SuspenseConditionStatus:
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"


class AdviceStatus:
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"
    REVERSED = "REVERSED"


class DemandReason:
    EPD = "EPD"
    DEFECT = "DEFECT"
    MISREPRESENTATION = "MISREPRESENTATION"


class DemandStatus:
    ISSUED = "ISSUED"
    APPEALED = "APPEALED"
    UPHELD = "UPHELD"
    RESCINDED = "RESCINDED"
    SATISFIED = "SATISFIED"


class DemandDecision:
    UPHOLD = "UPHOLD"
    RESCIND = "RESCIND"


class EscrowTransferStatus:
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    REVERSED = "REVERSED"


class EscrowReversalReason:
    REPURCHASE_SATISFIED = "REPURCHASE_SATISFIED"


class ScorecardStatus:
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ScorecardGrade:
    UNRATED = "UNRATED"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class StandingActionApplied:
    NONE = "NONE"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"
    RECOVERED = "RECOVERED"


# ─── Resource shapes ────────────────────────────────────────────────────────


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Seller(CommonFields, total=False):
    legal_name: str
    tin: str
    seller_type: str
    approval_status: str
    approval_tier: Optional[str]
    delivery_standing: str
    suspension_reason: Optional[str]
    approved_tangible_net_worth_cents: int
    mandatory_exposure_limit_cents: int
    open_mandatory_exposure_cents: int
    net_funded_cents: int
    fee_receivable_cents: int
    current_defect_rate_bps: int
    current_scorecard_grade: str
    servicing_retained_eligible: bool
    approval_decided_by_user_id: Optional[str]


class FinancialStatement(CommonFields, total=False):
    seller_id: str
    fiscal_year_end: str
    tangible_net_worth_cents: int
    liquid_assets_cents: int
    audited: bool
    status: str
    reviewed_by_user_id: Optional[str]


class QCReview(CommonFields, total=False):
    seller_id: str
    review_type: str
    status: str
    outcome: Optional[str]
    findings_count: int
    critical_findings_count: int
    completed_by_user_id: Optional[str]
    completed_at: Optional[str]


class Product(CommonFields, total=False):
    product_code: str
    description: Optional[str]
    base_price_pct: float
    min_fico: int
    max_ltv_pct: float
    max_loan_amount_cents: int
    allowed_commitment_types: list
    allowed_occupancies: list
    srp_pct: float
    status: str


class PricingAdjustment(CommonFields, total=False):
    product_id: str
    adjustment_code: str
    fico_min: int
    fico_max: int
    ltv_min_pct: float
    ltv_max_pct: float
    price_adjustment_bps: int
    status: str


class Commitment(CommonFields, total=False):
    seller_id: str
    product_id: str
    commitment_type: str
    status: str
    notional_amount_cents: int
    allocated_amount_cents: int
    fulfilled_amount_cents: int
    paired_off_amount_cents: int
    cancelled_amount_cents: int
    available_amount_cents: int
    tolerance_cents: int
    commitment_price_pct: float
    lock_term_days: int
    lock_term_bps: int
    llpa_bps_applied: int
    delivery_window_start: str
    delivery_expiry_date: str
    reference_fico: int
    reference_ltv_pct: float
    pair_off_fee_cents: int
    pair_off_market_price_pct: Optional[float]
    pair_off_method: Optional[str]
    locked_by_user_id: str


class Loan(CommonFields, total=False):
    commitment_id: str
    seller_id: str
    product_id: str
    seller_loan_number: str
    note_amount_cents: int
    note_rate_pct: float
    fico: int
    ltv_pct: float
    occupancy: str
    servicing_election: str
    closing_date: str
    first_payment_due_date: str
    escrow_balance_cents: int
    purchase_status: str
    first_payment_status: str
    review_cycle_count: int
    open_defect_count: int
    non_curable_defect_count: int
    open_suspense_count: int
    advice_count: int
    delivered_at: str
    purchased_at: Optional[str]


class Defect(CommonFields, total=False):
    loan_id: str
    defect_code: str
    category: str
    severity: str
    classification: str
    status: str
    description: Optional[str]
    price_adjustment_bps: int
    cure_deadline_at: Optional[str]
    cure_document_reference: Optional[str]
    cured_at: Optional[str]
    identified_by_user_id: str


class SuspenseCondition(CommonFields, total=False):
    loan_id: str
    condition_code: str
    description: Optional[str]
    status: str
    due_at: str
    document_reference: Optional[str]
    cleared_at: Optional[str]


class PurchaseAdvice(CommonFields, total=False):
    loan_id: str
    status: str
    final_purchase_price_pct: float
    volume_incentive_bps: int
    accrued_days: int
    principal_purchase_cents: int
    accrued_interest_cents: int
    escrow_funding_cents: int
    service_release_premium_cents: int
    defect_price_adjustment_cents: int
    wire_fee_cents: int
    net_wire_cents: int
    funding_reference: Optional[str]
    issued_by_user_id: str
    issued_at: str
    settled_by_user_id: Optional[str]
    settled_at: Optional[str]


class RepurchaseDemand(CommonFields, total=False):
    loan_id: str
    seller_id: str
    reason: str
    status: str
    demand_letter_reference: str
    source_defect_id: Optional[str]
    funding_recovery_cents: int
    admin_fee_cents: int
    repurchase_price_cents: int
    appeal_deadline_at: str
    appeal_reason: Optional[str]
    decision_note: Optional[str]
    remittance_reference: Optional[str]
    issued_by_user_id: str
    decided_by_user_id: Optional[str]
    satisfied_at: Optional[str]


class EscrowTransfer(CommonFields, total=False):
    loan_id: str
    status: str
    transfer_amount_cents: int
    transfer_due_at: str
    goodbye_letter_reference: Optional[str]
    completed_at: Optional[str]
    reversal_reason: Optional[str]


class SellerScorecard(CommonFields, total=False):
    seller_id: str
    period_start: str
    period_end: str
    status: str
    purchased_loan_count: int
    purchased_upb_cents: int
    defective_loan_count: int
    defective_upb_cents: int
    defect_rate_bps: int
    upb_weighted_defect_rate_bps: int
    grade: str
    breach: bool
    standing_action_applied: str
    closed_at: Optional[str]


JsonDict = dict[str, Any]
