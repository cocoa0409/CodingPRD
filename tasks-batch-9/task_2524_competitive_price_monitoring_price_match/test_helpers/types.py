"""Domain types for the Competitive Price Intelligence API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PRICING_ANALYST = "PricingAnalyst"
    PRICING_MANAGER = "PricingManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    DATA_COLLECTOR = "DataCollector"
    STORE_ASSOCIATE = "StoreAssociate"
    STORE_MANAGER = "StoreManager"


class StrategicPositioning(str, Enum):
    PRICE_LEADER = "PRICE_LEADER"
    AT_PARITY = "AT_PARITY"
    PREMIUM = "PREMIUM"


class PricingPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class CompetitorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class CollectionMethod(str, Enum):
    ONLINE = "ONLINE"
    STORE_AUDIT = "STORE_AUDIT"
    HYBRID = "HYBRID"


class CompetitorTier(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class MatchMethod(str, Enum):
    IDENTIFIER = "IDENTIFIER"
    ATTRIBUTE = "ATTRIBUTE"
    IMAGE = "IMAGE"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ConfidenceVariant(str, Enum):
    IDENTIFIER_ANCHORED = "IDENTIFIER_ANCHORED"
    ATTRIBUTE_BLEND = "ATTRIBUTE_BLEND"


class MatchGrade(str, Enum):
    EXACT = "EXACT"
    CLOSE = "CLOSE"
    WEAK = "WEAK"


class DataStatus(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class ObservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class IndexBasis(str, Enum):
    MATCHED_BASKET = "MATCHED_BASKET"
    IMPUTED_FULL_CATALOG = "IMPUTED_FULL_CATALOG"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class PositioningVerdict(str, Enum):
    ON_TARGET = "ON_TARGET"
    ABOVE_TARGET = "ABOVE_TARGET"
    BELOW_TARGET = "BELOW_TARGET"
    INDETERMINATE = "INDETERMINATE"


class PerceptionValidation(str, Enum):
    CONFIRMS = "CONFIRMS"
    CONTRADICTS = "CONTRADICTS"
    INDETERMINATE = "INDETERMINATE"


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class OrderOrigin(str, Enum):
    AUTOMATED_RULE = "AUTOMATED_RULE"
    MANUAL = "MANUAL"
    PRICE_MATCH = "PRICE_MATCH"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"


class SignageStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    QUEUED = "QUEUED"
    PRINTED = "PRINTED"
    RELEASED = "RELEASED"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFYING = "VERIFYING"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    HONORED = "HONORED"
    REVERSED = "REVERSED"


class ApprovalTier(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    MANAGER = "MANAGER"


class BatchStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PRINTING = "PRINTING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LedgerDirection(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


# --- Entity shapes -----------------------------------------------------------
# Every entity below carries id, created_at, updated_at and version, except
# OverrideLog, which is an append-only audit record carrying only id and
# created_at.


class Market(TypedDict):
    id: str
    market_code: str
    name: str
    currency_code: str
    strategic_positioning: str
    strategic_index_target_bp: int
    index_tolerance_bp: int
    observed_index_bp: Optional[int]
    positioning_gap_bp: Optional[int]
    insufficient_data_report_count: int
    pricing_posture: str
    created_at: str
    updated_at: str
    version: int


class Competitor(TypedDict):
    id: str
    market_id: str
    competitor_code: str
    name: str
    collection_method: str
    tier: str
    price_match_eligible: bool
    status: str
    suspension_reason: Optional[str]
    confirmed_match_count: int
    stale_match_count: int
    stale_share_bp: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    market_id: str
    sku: str
    category_code: str
    brand: str
    own_price_cents: int
    unit_cost_cents: int
    margin_floor_pct: float
    map_floor_cents: int
    brand_repricing_restricted: bool
    index_weight_bp: int
    status: str
    last_price_change_at: Optional[str]
    price_change_count: int
    effective_floor_cents: int
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    market_id: str
    store_code: str
    override_authority_cents: int
    label_printer_capacity_per_day: int
    label_slots_used_today: int
    label_slots_remaining_today: int
    override_budget_used_cents: int
    override_budget_remaining_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CompetitorProductLink(TypedDict):
    id: str
    product_id: str
    competitor_id: str
    match_method: str
    competitor_identifier: Optional[str]
    identifier_score: int
    attribute_score: int
    image_score: int
    confidence_bp: int
    confidence_variant: str
    match_grade: str
    review_round: int
    status: str
    latest_effective_price_cents: Optional[int]
    selected_observation_id: Optional[str]
    data_status: str
    gap_bp: Optional[int]
    gap_stale: bool
    created_at: str
    updated_at: str
    version: int


class PriceObservation(TypedDict):
    id: str
    link_id: str
    observed_price_cents: int
    collection_method: str
    observed_at: str
    in_stock: bool
    promo_flag: bool
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceIndexReport(TypedDict):
    id: str
    market_id: str
    category_code: str
    basis: str
    index_bp: Optional[int]
    candidate_product_count: int
    matched_product_count: int
    imputed_product_count: int
    excluded_product_count: int
    data_sufficiency: str
    positioning_gap_bp: Optional[int]
    positioning_verdict: str
    perception_survey_index_bp: Optional[int]
    perception_validation: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RepricingRule(TypedDict):
    id: str
    market_id: str
    category_code: str
    target_position_bp: int
    max_change_pct: float
    change_frequency_limit_days: int
    priority: int
    brand_exclusions: List[str]
    status: str
    applied_order_count: int
    created_at: str
    updated_at: str
    version: int


class PriceChangeOrder(TypedDict):
    id: str
    product_id: str
    market_id: str
    rule_id: Optional[str]
    source_claim_id: Optional[str]
    signage_store_id: Optional[str]
    supersedes_order_id: Optional[str]
    label_batch_id: Optional[str]
    origin: str
    requested_price_cents: Optional[int]
    benchmark_price_cents: Optional[int]
    target_price_cents: Optional[int]
    banded_price_cents: Optional[int]
    effective_floor_cents: int
    proposed_price_cents: int
    floor_binding: bool
    band_breach: bool
    effective_from: str
    effective_until: Optional[str]
    status: str
    signage_status: str
    authored_by_user_id: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceMatchPolicy(TypedDict):
    id: str
    market_id: str
    eligible_competitor_tiers: List[str]
    excluded_category_codes: List[str]
    verification_required: bool
    max_match_discount_pct: float
    daily_override_budget_cents: int
    claim_window_hours: int
    status: str
    honored_claim_count: int
    created_at: str
    updated_at: str
    version: int


class PriceMatchClaim(TypedDict):
    id: str
    policy_id: str
    product_id: str
    competitor_id: str
    store_id: str
    verification_link_id: Optional[str]
    claimed_price_cents: int
    claimed_observed_at: str
    competitor_evidence_ref: Optional[str]
    beat_bonus_cents: int
    honored_price_cents: int
    discount_cents: int
    required_approval_tier: str
    evidence_round: int
    status: str
    rejection_reason: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LabelPrintBatch(TypedDict):
    id: str
    store_id: str
    window_start: str
    window_end: str
    reserved_item_count: int
    queued_order_ids: List[str]
    item_count: int
    status: str
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OverrideLog(TypedDict):
    """Append-only audit record: carries only id and created_at."""
    id: str
    claim_id: str
    direction: str
    approval_tier: str
    approved_by_role: str
    approved_by_user_id: str
    approved_discount_cents: int
    honored_price_cents: int
    created_at: str
