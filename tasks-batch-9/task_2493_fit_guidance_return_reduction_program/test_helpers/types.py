"""Domain types for the Fit Guidance & Return Reduction Program API.

Entity TypedDicts, status enums and the operator role enum, all named exactly as
the PRD names them.  Twelve of the thirteen persisted resource types carry the
four system-managed properties described in PRD 2.4 (`id`, `created_at`,
`updated_at`, `version`); `ReturnCostPosting` is the exception and carries only
`id` and `created_at`.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    """The five recognized role names from PRD 2.1."""

    MERCH_OPS_ADMIN = "MerchOpsAdmin"
    VENDOR_USER = "VendorUser"
    FIT_ANALYST = "FitAnalyst"
    RETURNS_AUDITOR = "ReturnsAuditor"
    CUSTOMER = "Customer"


# ---------------------------------------------------------------------------
# Shared enumerations
# ---------------------------------------------------------------------------


class CategoryCode(str, Enum):
    TOPS = "TOPS"
    BOTTOMS = "BOTTOMS"
    DRESSES = "DRESSES"
    OUTERWEAR = "OUTERWEAR"
    FOOTWEAR = "FOOTWEAR"


class SizeSystem(str, Enum):
    US_ALPHA = "US_ALPHA"
    US_NUMERIC = "US_NUMERIC"
    EU = "EU"
    UK = "UK"


class MeasurementPoint(str, Enum):
    CHEST = "CHEST"
    WAIST = "WAIST"
    HIP = "HIP"
    INSEAM = "INSEAM"


class FabricStretchClass(str, Enum):
    RIGID = "RIGID"
    STRETCH = "STRETCH"
    HIGH_STRETCH = "HIGH_STRETCH"


# ---------------------------------------------------------------------------
# Per-entity status enums
# ---------------------------------------------------------------------------


class VendorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class ListingStatus(str, Enum):
    """The storefront axis of a catalog item (PRD 2.8)."""

    DRAFT = "DRAFT"
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class FitReadiness(str, Enum):
    """The fit-guidance axis of a catalog item (PRD 2.8)."""

    UNVERIFIED = "UNVERIFIED"
    CHART_MAPPED = "CHART_MAPPED"
    GUIDANCE_READY = "GUIDANCE_READY"


class FitWatchState(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    CHRONIC = "CHRONIC"


class DelistReasonCode(str, Enum):
    CHRONIC_FIT_RETURNS = "CHRONIC_FIT_RETURNS"
    VENDOR_EXIT = "VENDOR_EXIT"
    SEASONAL_END = "SEASONAL_END"
    MANUAL = "MANUAL"


class SpecStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    CORRECTION_REQUESTED = "CORRECTION_REQUESTED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class CorrectionReason(str, Enum):
    GRADE_TOLERANCE_VIOLATION = "GRADE_TOLERANCE_VIOLATION"
    CHRONIC_FIT_RETURNS = "CHRONIC_FIT_RETURNS"


class ChartStatus(str, Enum):
    DRAFT = "DRAFT"
    STANDARDIZED = "STANDARDIZED"
    RETIRED = "RETIRED"


class RetireReasonCode(str, Enum):
    SUPERSEDED_BY_NEW_CHART = "SUPERSEDED_BY_NEW_CHART"
    VENDOR_SYSTEM_CHANGE = "VENDOR_SYSTEM_CHANGE"
    DATA_QUALITY = "DATA_QUALITY"


class MappingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class SupersededReason(str, Enum):
    NEW_MAPPING = "NEW_MAPPING"
    CHART_RETIRED = "CHART_RETIRED"


class CustomerTier(str, Enum):
    STANDARD = "STANDARD"
    PLUS = "PLUS"


class AbuseStatus(str, Enum):
    CLEAR = "CLEAR"
    WATCH = "WATCH"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class PolicyClass(str, Enum):
    STANDARD_WINDOW = "STANDARD_WINDOW"
    EXTENDED_WINDOW = "EXTENDED_WINDOW"
    RESTRICTED_WINDOW = "RESTRICTED_WINDOW"


class OrderLineStatus(str, Enum):
    DELIVERED = "DELIVERED"
    RETURN_IN_PROGRESS = "RETURN_IN_PROGRESS"
    RETURNED = "RETURNED"
    KEPT = "KEPT"


class ReturnCaseStatus(str, Enum):
    TRIAGE = "TRIAGE"
    FIT_REVIEW = "FIT_REVIEW"
    QUALITY_REVIEW = "QUALITY_REVIEW"
    EXPECTATION_REVIEW = "EXPECTATION_REVIEW"
    COOLING_OFF = "COOLING_OFF"
    RESOLVED_REFUNDED = "RESOLVED_REFUNDED"
    RESOLVED_DENIED = "RESOLVED_DENIED"
    VOIDED = "VOIDED"


class ReasonCode(str, Enum):
    FIT_TOO_SMALL = "FIT_TOO_SMALL"
    FIT_TOO_LARGE = "FIT_TOO_LARGE"
    QUALITY_DEFECT = "QUALITY_DEFECT"
    EXPECTATION_MISMATCH = "EXPECTATION_MISMATCH"
    CHANGE_OF_MIND = "CHANGE_OF_MIND"


class ReasonFamily(str, Enum):
    FIT = "FIT"
    QUALITY = "QUALITY"
    EXPECTATION = "EXPECTATION"
    CHANGE_OF_MIND = "CHANGE_OF_MIND"


class ItemCondition(str, Enum):
    RESELLABLE_A = "RESELLABLE_A"
    RESELLABLE_B = "RESELLABLE_B"
    SALVAGE = "SALVAGE"


class VoidReason(str, Enum):
    AUDIT_REVERSAL = "AUDIT_REVERSAL"
    DUPLICATE_CASE = "DUPLICATE_CASE"
    FRAUD_CONFIRMED = "FRAUD_CONFIRMED"


class CostComponent(str, Enum):
    FREIGHT_INBOUND = "FREIGHT_INBOUND"
    PROCESSING_LABOR = "PROCESSING_LABOR"
    REFURB_REPACK = "REFURB_REPACK"
    MARKDOWN_LOSS = "MARKDOWN_LOSS"
    PAYMENT_FEE_UNRECOVERED = "PAYMENT_FEE_UNRECOVERED"
    VENDOR_CHARGEBACK_CREDIT = "VENDOR_CHARGEBACK_CREDIT"


class PostingKind(str, Enum):
    ORIGINAL = "ORIGINAL"
    REVERSAL = "REVERSAL"


class FitVerdict(str, Enum):
    TOO_SMALL = "TOO_SMALL"
    SLIGHTLY_SMALL = "SLIGHTLY_SMALL"
    TRUE_TO_SIZE = "TRUE_TO_SIZE"
    SLIGHTLY_LARGE = "SLIGHTLY_LARGE"
    TOO_LARGE = "TOO_LARGE"


class FeedbackStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"


class RetractReason(str, Enum):
    AUTHOR_WITHDRAWN = "AUTHOR_WITHDRAWN"
    MODERATION_REMOVED = "MODERATION_REMOVED"


class PolicyScope(str, Enum):
    CATEGORY_DEFAULT = "CATEGORY_DEFAULT"
    CUSTOMER_OVERRIDE = "CUSTOMER_OVERRIDE"


class Lever(str, Enum):
    SIZE_CHART_STANDARDIZATION = "SIZE_CHART_STANDARDIZATION"
    PDP_MODEL_MEASUREMENTS = "PDP_MODEL_MEASUREMENTS"
    DETAIL_IMAGERY = "DETAIL_IMAGERY"
    FIT_RECOMMENDATION_BADGE = "FIT_RECOMMENDATION_BADGE"
    VENDOR_SPEC_CORRECTION = "VENDOR_SPEC_CORRECTION"


class FundingPosture(str, Enum):
    FUNDED = "FUNDED"
    UNDER_REVIEW = "UNDER_REVIEW"
    DEFUNDED = "DEFUNDED"


class DeploymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    MEASURED = "MEASURED"


class TerminatedReasonCode(str, Enum):
    WINDOW_ELAPSED = "WINDOW_ELAPSED"
    ITEM_DELISTED = "ITEM_DELISTED"
    MAPPING_SUPERSEDED = "MAPPING_SUPERSEDED"
    MANUAL_STOP = "MANUAL_STOP"


class SavingsVariant(str, Enum):
    DEPLOYMENT_ATTRIBUTED = "deployment_attributed"
    COHORT_CHRONOLOGICAL = "cohort_chronological"


class RecommendationVariant(str, Enum):
    HISTORY_WEIGHTED = "history_weighted"
    POPULATION_FALLBACK = "population_fallback"


# ---------------------------------------------------------------------------
# Nested value objects
# ---------------------------------------------------------------------------


class SizePoint(TypedDict):
    size_label: str
    sort_index: int
    chest_mm: int
    waist_mm: int
    hip_mm: int
    inseam_mm: int


class GradeRule(TypedDict):
    measurement_point: str
    increment_mm: int
    tolerance_pct_bp: int
    tolerance_abs_mm: int


class ToleranceApplied(TypedDict):
    measurement_point: str
    tolerance_mm: int


class ChartRow(TypedDict):
    size_label: str
    sort_index: int
    body_chest_min_mm: int
    body_chest_max_mm: int
    body_waist_min_mm: int
    body_waist_max_mm: int
    conversion_us_alpha: str
    conversion_us_numeric: str
    conversion_eu: str
    conversion_uk: str


class SizeLabelPair(TypedDict):
    spec_size_label: str
    chart_size_label: str


# ---------------------------------------------------------------------------
# Entities carrying the four common resource properties (PRD 2.4)
# ---------------------------------------------------------------------------


class Vendor(TypedDict):
    id: str
    name: str
    brand_code: str
    correction_budget_cents: int
    correction_spend_cents: int
    correction_round_count: int
    quality_chargeback_count: int
    reliability_score_bp: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CatalogItem(TypedDict):
    id: str
    vendor_id: str
    sku: str
    category_code: str
    brand_size_system: str
    unit_price_cents: int
    listing_status: str
    fit_readiness: str
    fit_watch_state: str
    model_measurements_published: bool
    model_height_cm: Optional[int]
    model_worn_size_label: Optional[str]
    detail_image_count: int
    pdp_review_required: bool
    units_sold_count: int
    fit_return_count: int
    expectation_return_count: int
    total_return_count: int
    fit_return_rate_bp: int
    expectation_return_rate_bp: int
    chronic_return_score_bp: int
    return_cost_accrued_cents: int
    fit_signal_weight_total: int
    active_fit_feedback_count: int
    delist_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeasurementSpec(TypedDict):
    id: str
    item_id: str
    revision_round: int
    status: str
    size_system: str
    base_size_label: str
    fabric_stretch_class: str
    size_points: List[SizePoint]
    grade_rules: List[GradeRule]
    violation_count: int
    first_violation_point: Optional[str]
    first_violation_from_size_label: Optional[str]
    tolerance_applied_mm: Optional[List[ToleranceApplied]]
    correction_reason: Optional[str]
    verified_by_user_id: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SizeChart(TypedDict):
    id: str
    chart_code: str
    size_system: str
    category_code: str
    status: str
    rows: List[ChartRow]
    row_count: int
    median_row_index: int
    retire_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SizeChartMapping(TypedDict):
    id: str
    item_id: str
    chart_id: str
    size_label_pairs: List[SizeLabelPair]
    mapped_row_count: int
    spec_size_point_count: int
    coverage_bp: int
    unmapped_size_labels: List[str]
    status: str
    superseded_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CustomerProfile(TypedDict):
    id: str
    email: str
    tier: str
    purchase_line_count: int
    return_case_count: int
    change_of_mind_count: int
    return_rate_bp: int
    abuse_strike_count: int
    abuse_status: str
    policy_class: str
    refunded_total_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    customer_profile_id: str
    item_id: str
    size_label: str
    quantity: int
    unit_price_cents: int
    shipping_allocated_cents: int
    delivered_at: str
    gross_line_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReturnCase(TypedDict):
    id: str
    order_line_id: str
    requested_reason_code: str
    reason_code: str
    reason_family: str
    status: str
    effective_policy_id: str
    effective_window_days: int
    return_deadline_at: str
    requested_at: str
    item_condition: Optional[str]
    restocking_fee_cents: int
    refund_amount_cents: int
    total_cost_cents: int
    classified_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FitFeedback(TypedDict):
    id: str
    item_id: str
    customer_profile_id: str
    purchased_size_label: str
    fit_verdict: str
    comment: Optional[str]
    verdict_offset_centi: int
    signal_weight: int
    status: str
    retract_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnPolicy(TypedDict):
    id: str
    scope: str
    customer_profile_id: Optional[str]
    category_code: str
    window_days: int
    restocking_applies: bool
    non_refundable_shipping: bool
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Intervention(TypedDict):
    id: str
    name: str
    lever: str
    unit_cost_cents: int
    deployment_count: int
    measured_deployment_count: int
    gross_savings_cents: int
    spend_cents: int
    net_savings_cents: int
    funding_posture: str
    created_at: str
    updated_at: str
    version: int


class InterventionDeployment(TypedDict):
    id: str
    intervention_id: str
    item_id: str
    window_start: str
    window_end: str
    spend_cents: int
    status: str
    baseline_units_count: Optional[int]
    baseline_return_rate_bp: Optional[int]
    window_units_count: Optional[int]
    measured_return_rate_bp: Optional[int]
    avoided_return_count: Optional[int]
    attributed_savings_cents: Optional[int]
    terminated_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# The immutable ledger line — only id and created_at (PRD 2.4)
# ---------------------------------------------------------------------------


class ReturnCostPosting(TypedDict):
    """An immutable ledger line.  It has no `updated_at` and no `version`, and
    those keys must be absent from its representation rather than present and
    null."""

    id: str
    return_case_id: str
    component: str
    amount_cents: int
    posting_kind: str
    reversed_component: Optional[str]
    created_at: str


# ---------------------------------------------------------------------------
# Computed read payloads (not persisted rows)
# ---------------------------------------------------------------------------


class FitRecommendation(TypedDict):
    recommended_size_label: Optional[str]
    confidence_bp: int
    variant_applied: str
    sample_count: int
    coverage_bp: int
    suppressed: bool
    anchor_index: int
    recommended_index: int


class SavingsReport(TypedDict):
    variant_applied: str
    gross_savings_cents: int
    spend_cents: int
    net_savings_cents: int
    measured_deployment_count: int
    avoided_return_count: int
    funding_posture: str


class OpsRunSummary(TypedDict):
    deployments_activated: int
    deployments_terminated: int
    deployments_measured: int
    items_swept: int
    watch_flips: int
    chronic_flips: int
    corrections_opened: int
    abuse_downgrades: int


JsonDict = Dict[str, Any]
