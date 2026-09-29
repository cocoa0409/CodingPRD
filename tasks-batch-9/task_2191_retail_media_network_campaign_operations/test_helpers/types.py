"""Typed shapes for every resource the retail media network API returns.

Each TypedDict lists the fields the PRD says a read of that resource returns:
client-supplied inputs plus every derived figure. Enum value tuples are given
alongside so a test can assert membership rather than restate a literal.

Thirteen of the fifteen resources carry the full common field set — `id`,
`created_at`, `updated_at` and `version`. AuctionBid and EngagementEvent are
append-only records that are never amended, so they carry only `id` and
`created_at` and have no `version` to check.
"""

from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enumerated values
# ---------------------------------------------------------------------------

ADVERTISER_SERVICE_MODEL_VALUES = (
    "SELF_SERVE",
    "MANAGED",
)
ADVERTISER_ONBOARDING_STATUS_VALUES = (
    "DRAFT",
    "SUBMITTED",
    "KYC_REVIEW",
    "CREDIT_HOLD",
    "ACTIVE",
    "SUSPENDED",
    "REJECTED",
    "TERMINATED",
)
ADVERTISER_SUSPENSION_REASON_VALUES = (
    "NONE",
    "CREDIT_BREACH",
    "COMPLIANCE",
    "MANUAL",
)
BUDGET_PLAN_PLAN_STATUS_VALUES = (
    "DRAFT",
    "PENDING_APPROVAL",
    "APPROVED",
    "ACTIVE",
    "EXHAUSTED",
    "CLOSED",
    "REJECTED",
)
TRADE_FUND_ACCOUNT_ACCOUNT_STATUS_VALUES = (
    "OPEN",
    "FROZEN",
    "RECONCILING",
    "CLOSED",
)
TRADE_FUND_ACCOUNT_ACCRUAL_BASIS_VALUES = (
    "PURCHASE_VOLUME",
    "FIXED",
)
TRADE_FUND_ACCOUNT_FROZEN_REASON_VALUES = (
    "NONE",
    "AUDIT",
    "OVERDRAWN",
    "MANUAL",
)
CAMPAIGN_CHANNEL_MIX_VALUES = (
    "ONSITE_ONLY",
    "OFFSITE_ONLY",
    "OMNI",
)
CAMPAIGN_DELIVERY_STATUS_VALUES = (
    "DRAFT",
    "PENDING_REVIEW",
    "SCHEDULED",
    "DELIVERING",
    "PAUSED",
    "COMPLETED",
    "REJECTED",
    "ARCHIVED",
)
CAMPAIGN_BILLING_STATUS_VALUES = (
    "UNBILLED",
    "ACCRUING",
    "PENDING_INVOICE",
    "INVOICED",
    "DISPUTED",
    "RECONCILED",
)
CAMPAIGN_PACING_MODE_VALUES = (
    "EVEN",
    "ACCELERATED",
)
CAMPAIGN_ATTRIBUTION_MODEL_VALUES = (
    "LAST_TOUCH",
    "FRACTIONAL",
)
PLACEMENT_SLOT_CHANNEL_VALUES = (
    "ONSITE",
    "OFFSITE",
)
PLACEMENT_SLOT_PAGE_TYPE_VALUES = (
    "SEARCH_RESULTS",
    "CATEGORY_BROWSE",
    "PRODUCT_DETAIL",
    "HOMEPAGE",
    "OFFSITE_SOCIAL",
    "OFFSITE_DISPLAY",
)
PLACEMENT_SLOT_SLOT_STATUS_VALUES = (
    "OPEN",
    "MAINTENANCE",
    "RETIRED",
)
LINE_ITEM_LINE_ITEM_STATUS_VALUES = (
    "DRAFT",
    "PENDING_ELIGIBILITY",
    "ELIGIBLE",
    "SERVING",
    "OOS_PAUSED",
    "MANUAL_PAUSED",
    "REJECTED",
    "ENDED",
)
LINE_ITEM_BID_TYPE_VALUES = (
    "CPC",
    "CPM",
)
LINE_ITEM_PRIORITY_TIER_VALUES = (
    "TIER_1",
    "TIER_2",
    "TIER_3",
)
LINE_ITEM_PAUSE_REASON_VALUES = (
    "NONE",
    "OUT_OF_STOCK",
    "MANUAL",
    "BUDGET_EXHAUSTED",
    "CATALOG_RESTRICTED",
)
CATALOG_PRODUCT_ELIGIBILITY_STATUS_VALUES = (
    "ELIGIBLE",
    "OUT_OF_STOCK",
    "RESTRICTED",
    "DELISTED",
)
CATALOG_PRODUCT_RESTRICTED_REASON_VALUES = (
    "NONE",
    "AGE_RESTRICTED",
    "REGULATORY",
    "BRAND_SAFETY",
)
PRODUCT_ASSIGNMENT_ASSIGNMENT_STATUS_VALUES = (
    "ACTIVE",
    "PAUSED_OOS",
    "PAUSED_RESTRICTED",
    "REMOVED",
)
AUCTION_EVENT_STATUS_VALUES = (
    "OPEN",
    "RANKED",
    "AWARDED",
    "NO_FILL",
    "SETTLED",
)
AUCTION_EVENT_SHOPPER_SEGMENT_VALUES = (
    "NEW",
    "RETURNING",
    "LOYALTY",
)
AUCTION_EVENT_NO_FILL_REASON_VALUES = (
    "NONE",
    "NO_ELIGIBLE_CANDIDATES",
    "ALL_BELOW_FLOOR",
    "BUDGET_EXHAUSTED",
)
AUCTION_BID_OUTCOME_VALUES = (
    "WON",
    "LOST",
    "FILTERED_INELIGIBLE",
    "FILTERED_BELOW_FLOOR",
)
AUCTION_BID_FILTER_REASON_VALUES = (
    "NONE",
    "NOT_SERVING",
    "NO_ELIGIBLE_PRODUCTS",
    "ZERO_TERM_OVERLAP",
    "DAILY_BUDGET_EXHAUSTED",
    "BELOW_FLOOR",
)
ENGAGEMENT_EVENT_EVENT_TYPE_VALUES = (
    "IMPRESSION",
    "CLICK",
    "OFFSITE_VIEW",
)
ENGAGEMENT_EVENT_CHANNEL_VALUES = (
    "ONSITE",
    "OFFSITE",
)
ATTRIBUTED_SALE_MATCH_TYPE_VALUES = (
    "CLICK_THROUGH",
    "VIEW_THROUGH",
)
ATTRIBUTED_SALE_ATTRIBUTION_MODEL_APPLIED_VALUES = (
    "LAST_TOUCH",
    "FRACTIONAL",
)
INCREMENTALITY_STUDY_STUDY_STATUS_VALUES = (
    "DESIGNED",
    "RUNNING",
    "MEASURING",
    "PUBLISHED",
    "INVALIDATED",
)
INCREMENTALITY_STUDY_DESIGN_METHOD_VALUES = (
    "GEO_HOLDOUT",
    "USER_HOLDOUT",
)
INCREMENTALITY_STUDY_INVALIDATED_REASON_VALUES = (
    "NONE",
    "DATA_DEFECT",
    "HOLDOUT_CONTAMINATION",
    "SUPERSEDED",
)
INVOICE_INVOICE_STATUS_VALUES = (
    "DRAFT",
    "ISSUED",
    "DISPUTED",
    "ADJUSTED",
    "SETTLED",
    "WRITTEN_OFF",
)
MEASUREMENT_DISPUTE_DISPUTE_STATUS_VALUES = (
    "SUBMITTED",
    "UNDER_REVIEW",
    "INFO_REQUESTED",
    "UPHELD",
    "REJECTED",
    "ESCALATED",
    "WITHDRAWN",
)
MEASUREMENT_DISPUTE_DISPUTE_CATEGORY_VALUES = (
    "IMPRESSION_DISCREPANCY",
    "ATTRIBUTION_WINDOW",
    "OFFSITE_SPEND_VARIANCE",
    "INCREMENTALITY_RESTATEMENT",
)


# ---------------------------------------------------------------------------
# Resource shapes
# ---------------------------------------------------------------------------


class Advertiser(TypedDict, total=False):
    """Shape of a Advertiser read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    brand_code: str
    service_model: str
    onboarding_status: str
    parent_advertiser_id: Optional[str]
    account_manager_user_id: Optional[str]
    credit_limit_cents: int
    credit_exposure_cents: int
    kyc_document_count: int
    suspension_reason: str
    self_serve_daily_spend_cap_cents: int
    managed_service_fee_pct: float
    dispute_credit_balance_cents: int
    onboarding_submitted_by_user_id: str
    kyc_decided_by_user_id: Optional[str]


class BudgetPlan(TypedDict, total=False):
    """Shape of a BudgetPlan read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    advertiser_id: str
    fiscal_period_code: str
    plan_status: str
    committed_total_cents: int
    trade_fund_share_cents: int
    cash_share_cents: int
    reserved_cents: int
    consumed_cents: int
    available_cents: int
    top_up_total_cents: int
    window_start_at: str
    window_end_at: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    revision_round: int
    exhausted_at: Optional[str]


class TradeFundAccount(TypedDict, total=False):
    """Shape of a TradeFundAccount read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    advertiser_id: str
    fiscal_period_code: str
    account_status: str
    accrual_basis: str
    deduction_cap_pct: float
    accrued_cents: int
    reserved_cents: int
    deducted_cents: int
    available_cents: int
    frozen_reason: str
    last_reconciled_at: Optional[str]


class Campaign(TypedDict, total=False):
    """Shape of a Campaign read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    advertiser_id: str
    budget_plan_id: str
    name: str
    channel_mix: str
    delivery_status: str
    billing_status: str
    flight_start_at: str
    flight_end_at: str
    pacing_mode: str
    daily_cap_cents: int
    allocated_budget_cents: int
    attribution_model: str
    attribution_window_days: int
    delivered_spend_cents: int
    offsite_reported_spend_cents: int
    offsite_variance_pct: float
    attributed_revenue_cents: int
    incremental_revenue_cents: int
    roas: float
    iroas: float
    pacing_index: float
    oos_paused_line_item_count: int
    review_decided_by_user_id: Optional[str]
    submitted_for_review_by_user_id: Optional[str]


class PlacementSlot(TypedDict, total=False):
    """Shape of a PlacementSlot read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    slot_code: str
    channel: str
    page_type: str
    position_index: int
    max_concurrent_line_items: int
    floor_cpc_cents: int
    exclusivity_category_code: Optional[str]
    buffer_minutes: int
    slot_status: str
    relevance_weight: float
    occupancy_count: int


class LineItem(TypedDict, total=False):
    """Shape of a LineItem read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    campaign_id: str
    placement_slot_id: str
    line_item_status: str
    bid_cents: int
    bid_type: str
    flight_start_at: str
    flight_end_at: str
    daily_budget_cents: int
    category_code: str
    keyword_match_terms: List[str]
    reserved_cents: int
    spend_cents: int
    eligible_product_count: int
    relevance_score: float
    quality_adjusted_score: float
    priority_tier: str
    pause_reason: str
    last_pause_at: Optional[str]
    eligibility_decided_by_user_id: Optional[str]


class CatalogProduct(TypedDict, total=False):
    """Shape of a CatalogProduct read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    sku: str
    category_code: str
    title: str
    price_cents: int
    in_stock_units: int
    min_stock_units_for_serving: int
    eligibility_status: str
    restricted_reason: str
    margin_pct: float
    last_stock_change_at: Optional[str]


class ProductAssignment(TypedDict, total=False):
    """Shape of a ProductAssignment read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    line_item_id: str
    catalog_product_id: str
    assignment_status: str
    is_hero: bool
    relevance_contribution: float
    removed_at: Optional[str]


class AuctionEvent(TypedDict, total=False):
    """Shape of a AuctionEvent read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    placement_slot_id: str
    winning_line_item_id: Optional[str]
    status: str
    request_context_query: str
    shopper_segment: str
    requested_at: str
    candidate_count: int
    winner_score: Optional[float]
    second_best_score: Optional[float]
    clearing_price_cents: Optional[int]
    settled_spend_cents: int
    no_fill_reason: str


class AuctionBid(TypedDict, total=False):
    """Shape of a AuctionBid read. Append-only: no updated_at and no version."""

    id: str
    created_at: str
    auction_event_id: str
    line_item_id: str
    raw_bid_cents: int
    relevance_score: float
    quality_adjusted_score: float
    rank: Optional[int]
    outcome: str
    filter_reason: str


class EngagementEvent(TypedDict, total=False):
    """Shape of a EngagementEvent read. Append-only: no updated_at and no version."""

    id: str
    created_at: str
    line_item_id: str
    auction_event_id: str
    catalog_product_id: str
    event_type: str
    occurred_at: str
    shopper_hash: str
    channel: str
    billable_cents: int


class AttributedSale(TypedDict, total=False):
    """Shape of a AttributedSale read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    engagement_event_id: str
    line_item_id: str
    catalog_product_id: str
    retail_order_ref: str
    sale_cents: int
    units: int
    occurred_at: str
    match_type: str
    attribution_model_applied: str
    attribution_weight: float
    attributed_credit_cents: int
    within_window: bool
    restated: bool


class IncrementalityStudy(TypedDict, total=False):
    """Shape of a IncrementalityStudy read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    campaign_id: str
    supersedes_study_id: Optional[str]
    study_status: str
    design_method: str
    holdout_pct: float
    exposed_group_size: int
    control_group_size: int
    exposed_conversions: int
    control_conversions: int
    exposed_sales_cents: int
    control_sales_cents: int
    lift_pct: float
    incremental_sales_cents: int
    significance_score: float
    significance_flag: bool
    window_start_at: str
    window_end_at: str
    published_by_user_id: Optional[str]
    invalidated_reason: str


class Invoice(TypedDict, total=False):
    """Shape of a Invoice read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    advertiser_id: str
    budget_plan_id: str
    trade_fund_account_id: Optional[str]
    invoice_status: str
    billing_period_code: str
    onsite_spend_cents: int
    offsite_spend_cents: int
    gross_spend_cents: int
    managed_service_fee_cents: int
    trade_fund_deduction_cents: int
    dispute_credit_cents: int
    net_cash_due_cents: int
    variance_pct: float
    adjustment_round: int
    issued_at: Optional[str]
    due_at: Optional[str]
    settled_at: Optional[str]
    issued_by_user_id: Optional[str]


class MeasurementDispute(TypedDict, total=False):
    """Shape of a MeasurementDispute read."""

    id: str
    created_at: str
    updated_at: str
    version: int
    invoice_id: str
    line_item_id: Optional[str]
    dispute_status: str
    dispute_category: str
    claimed_amount_cents: int
    approved_credit_cents: int
    filed_at: str
    sla_response_hours: int
    sla_due_at: str
    first_response_at: Optional[str]
    info_request_count: int
    review_rounds: int
    sla_breached: bool
    escalation_level: int
    assigned_analyst_user_id: Optional[str]
    resolved_by_user_id: Optional[str]

