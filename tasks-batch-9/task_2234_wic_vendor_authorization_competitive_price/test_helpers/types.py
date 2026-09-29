"""
Typed shapes and enumerations for the WIC vendor authorization API.

The TypedDicts mirror the field sets the PRD says every read and list endpoint
exposes. They are documentation for the test author first and type hints second,
so they are declared ``total=False``: a test asserts the fields it cares about.
Every resource in this API carries ``id``, ``created_at``, ``updated_at`` and
``version`` (PRD 2.4).
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role(str, Enum):
    """The five declared role names (PRD 2.1)."""

    VENDOR_OPERATOR = "VendorOperator"
    VENDOR_UNIT_ANALYST = "VendorUnitAnalyst"
    VENDOR_UNIT_SUPERVISOR = "VendorUnitSupervisor"
    COMPLIANCE_INVESTIGATOR = "ComplianceInvestigator"
    SYSTEM_OPERATOR = "SystemOperator"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class StoreType(str, Enum):
    SUPERMARKET = "SUPERMARKET"
    SUPERSTORE = "SUPERSTORE"
    MEDIUM_GROCERY = "MEDIUM_GROCERY"
    SMALL_GROCERY = "SMALL_GROCERY"
    PHARMACY = "PHARMACY"


class MarMethod(str, Enum):
    PEER_MEDIAN = "PEER_MEDIAN"
    PEER_PERCENTILE_75 = "PEER_PERCENTILE_75"
    LOWEST_HALF_AVG = "LOWEST_HALF_AVG"


class PeerGroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class FormulaRestrictionLevel(str, Enum):
    NONE = "NONE"
    CONTRACT_BRAND_ONLY = "CONTRACT_BRAND_ONLY"
    MEDICAL_DOC_REQUIRED = "MEDICAL_DOC_REQUIRED"


class FoodItemStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELISTED = "DELISTED"


class VendorStatus(str, Enum):
    APPLICANT = "APPLICANT"
    IN_REVIEW = "IN_REVIEW"
    AUTHORIZED = "AUTHORIZED"
    REAUTH_PENDING = "REAUTH_PENDING"
    SUSPENDED = "SUSPENDED"
    DISQUALIFIED = "DISQUALIFIED"
    DENIED = "DENIED"


class TrainingType(str, Enum):
    INITIAL = "INITIAL"
    ANNUAL = "ANNUAL"
    CORRECTIVE = "CORRECTIVE"


class RiskTier(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    HIGH = "HIGH"


class RiskFlag(str, Enum):
    NONE = "NONE"
    HIGH_FINDING_COUNT = "HIGH_FINDING_COUNT"
    HIGH_SCORE = "HIGH_SCORE"


class RiskBasis(str, Enum):
    ROLLING = "ROLLING"
    EPOCH = "EPOCH"


class BlockedReason(str, Enum):
    PEER_GROUP_RETIRED = "PEER_GROUP_RETIRED"
    PENDING_COMPLIANCE_BUY = "PENDING_COMPLIANCE_BUY"


class PriceCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PUBLISHED = "PUBLISHED"


class SubmissionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class ReviewDecision(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class ReviewReason(str, Enum):
    PRICE_IMPLAUSIBLE = "PRICE_IMPLAUSIBLE"
    MISSING_DOCUMENTATION = "MISSING_DOCUMENTATION"
    ABOVE_STATEWIDE_OUTLIER = "ABOVE_STATEWIDE_OUTLIER"


class VoidedReason(str, Enum):
    ITEM_DELISTED = "ITEM_DELISTED"
    VENDOR_DISQUALIFIED = "VENDOR_DISQUALIFIED"


class CeilingStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class SupersededReason(str, Enum):
    PROVISIONAL_REPLACED = "PROVISIONAL_REPLACED"
    NEWER_CYCLE_PUBLISHED = "NEWER_CYCLE_PUBLISHED"
    ITEM_DELISTED = "ITEM_DELISTED"


class CeilingBasis(str, Enum):
    PEER_GROUP = "PEER_GROUP"
    STATEWIDE_FALLBACK = "STATEWIDE_FALLBACK"


class VisitType(str, Enum):
    ROUTINE = "ROUTINE"
    COMPLIANCE_BUY = "COMPLIANCE_BUY"
    HIGH_RISK_FOLLOWUP = "HIGH_RISK_FOLLOWUP"


class VisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CURED = "CURED"
    ESCALATED = "ESCALATED"
    CANCELLED = "CANCELLED"


class VisitOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL_MISSING_CATEGORY = "FAIL_MISSING_CATEGORY"
    FAIL_BELOW_MINIMUM = "FAIL_BELOW_MINIMUM"
    FAIL_PRICE_OVERCHARGE = "FAIL_PRICE_OVERCHARGE"


class StockVerdict(str, Enum):
    MISSING = "MISSING"
    BELOW_UNITS = "BELOW_UNITS"
    BELOW_VARIETY = "BELOW_VARIETY"
    PASS = "PASS"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"
    ADJUSTED = "ADJUSTED"
    PAID = "PAID"


class EditResult(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    ACCEPTED_REDUCED = "ACCEPTED_REDUCED"
    REJECTED = "REJECTED"


class EditCode(str, Enum):
    E01 = "E01"
    E02 = "E02"
    E03 = "E03"
    E04 = "E04"
    E05 = "E05"


class AdjustmentStatus(str, Enum):
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


class AdjustmentReasonCode(str, Enum):
    OVERCHARGE = "OVERCHARGE"
    EDIT_ERROR = "EDIT_ERROR"
    COMPLIANCE_BUY_FINDING = "COMPLIANCE_BUY_FINDING"
    CMP_OFFSET = "CMP_OFFSET"


class ViolationCode(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"
    CLASS_D = "CLASS_D"


class SanctionStatus(str, Enum):
    OPENED = "OPENED"
    NOTICE_SERVED = "NOTICE_SERVED"
    CMP_ELECTED = "CMP_ELECTED"
    DISQUALIFICATION_IMPOSED = "DISQUALIFICATION_IMPOSED"
    DISMISSED = "DISMISSED"
    CLOSED = "CLOSED"


class SanctionResolution(str, Enum):
    NONE = "NONE"
    CMP = "CMP"
    DISQUALIFICATION = "DISQUALIFICATION"
    DISMISSED = "DISMISSED"


# The literal principal recorded for a case opened by the risk run (PRD 2.10).
SYSTEM_PRINCIPAL = "SYSTEM"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class CommonFields(TypedDict, total=False):
    """The four system-managed properties every resource carries (PRD 2.4)."""

    id: str
    created_at: str
    updated_at: str
    version: int


class PeerGroup(CommonFields, total=False):
    code: str
    store_type: str
    min_monthly_redemption_cents: int
    max_monthly_redemption_cents: Optional[int]
    mar_method: str
    competitive_allowance_pct: float
    min_submissions_for_ceiling: int
    min_stock_multiplier: float
    status: str
    member_count: int
    retired_at: Optional[str]


class FoodCategory(CommonFields, total=False):
    code: str
    name: str
    is_formula: bool
    formula_restriction_level: str
    min_stock_units: int
    min_variety_count: int
    max_units_per_transaction: int
    stock_required: bool


class AuthorizedFoodItem(CommonFields, total=False):
    food_category_id: str
    upc: str
    brand: str
    container_size_oz: float
    contract_brand: bool
    required_for_authorization: bool
    status: str
    delisted_at: Optional[str]
    delist_reason: Optional[str]


class Vendor(CommonFields, total=False):
    store_name: str
    store_type: str
    reported_monthly_redemption_cents: int
    authorization_status: str
    peer_group_id: Optional[str]
    authorized_at: Optional[str]
    reauthorization_due_at: Optional[str]
    reauth_completed_count: int
    reauthorization_hold: bool
    reauth_blocked_reason: Optional[str]
    authorization_blocked_reason: Optional[str]
    training_type: Optional[str]
    training_completed_at: Optional[str]
    training_expires_at: Optional[str]
    accepted_submission_count: int
    price_submission_complete: bool
    open_finding_count: int
    cure_deadline_at: Optional[str]
    compliance_buy_required: bool
    risk_score: float
    risk_tier: str
    risk_flag: Optional[str]
    risk_epoch_at: Optional[str]
    sanction_points: int
    disqualified_until: Optional[str]
    denial_reason: Optional[str]
    recoupment_balance_cents: int
    avg_monthly_redemption_cents: int


class PriceCycle(CommonFields, total=False):
    cycle_code: str
    submission_open_at: str
    submission_due_at: str
    status: str
    closed_at: Optional[str]
    published_at: Optional[str]
    provisional_ceiling_count: int
    published_ceiling_count: int
    skipped_pair_count: int


class PriceSubmission(CommonFields, total=False):
    vendor_id: str
    food_item_id: str
    price_cycle_id: str
    shelf_price_cents: int
    status: str
    revision_count: int
    review_reason: Optional[str]
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]
    voided_reason: Optional[str]


class PriceCeiling(CommonFields, total=False):
    peer_group_id: str
    food_item_id: str
    price_cycle_id: str
    basis: str
    peer_submission_count: int
    contributing_submission_count: int
    base_cents: float
    cap_cents: float
    cap_binding: bool
    mar_cents: int
    status: str
    superseded_reason: Optional[str]
    effective_from: str


class StockFinding(TypedDict, total=False):
    food_category_id: str
    observed_units: int
    observed_variety_count: int
    required_units: Optional[int]
    verdict: Optional[str]


class MonitoringVisit(CommonFields, total=False):
    vendor_id: str
    visit_type: str
    scheduled_for: str
    status: str
    outcome: str
    auto_generated: bool
    conducted_at: Optional[str]
    cancelled_reason: Optional[str]
    overcharge_cents: int
    stock_compliance_pct: float
    stock_findings: List[StockFinding]


class RedemptionClaim(CommonFields, total=False):
    vendor_id: str
    claim_month: str
    status: str
    line_count: int
    submitted_total_cents: int
    governing_price_cycle_id: Optional[str]
    adjudicated_total_cents: Optional[int]
    net_payable_cents: Optional[int]
    adjudicated_at: Optional[str]
    paid_at: Optional[str]
    accepted_line_count: int
    reduced_line_count: int
    rejected_line_count: int


class ClaimLine(CommonFields, total=False):
    redemption_claim_id: str
    line_number: int
    upc: str
    quantity: int
    charged_unit_price_cents: int
    medical_doc_on_file: bool
    food_item_id: Optional[str]
    edit_result: str
    edit_code: Optional[str]
    applied_mar_cents: Optional[int]
    allowed_cents: int
    recouped_cents: int


class LineRecoupment(TypedDict, total=False):
    claim_line_id: str
    allowed_cents: int
    recoupment_cents: int


class ReimbursementAdjustment(CommonFields, total=False):
    redemption_claim_id: str
    reason_code: str
    recoupment_rate: float
    recoupment_cents: int
    line_recoupments: List[LineRecoupment]
    status: str
    created_by_user_id: str
    applied_by_user_id: Optional[str]
    applied_at: Optional[str]
    reversed_at: Optional[str]
    reversal_reason: Optional[str]


class SanctionCase(CommonFields, total=False):
    vendor_id: str
    violation_code: str
    source_visit_id: Optional[str]
    narrative: str
    base_tier: int
    case_points: int
    cumulative_points_at_open: int
    effective_tier: int
    disqualification_months: int
    cmp_permitted: bool
    cmp_amount_cents: int
    cmp_paid_cents: int
    status: str
    resolution: str
    opened_by_user_id: str
    notice_served_at: Optional[str]
    response_due_at: Optional[str]
    dismissal_reason: Optional[str]


# Free-form aliases for the two computed reads and the two operational responses.
RiskProfile = Dict[str, Any]
PublishSummary = Dict[str, Any]
RiskRunSummary = Dict[str, Any]
ClockResponse = Dict[str, Any]
