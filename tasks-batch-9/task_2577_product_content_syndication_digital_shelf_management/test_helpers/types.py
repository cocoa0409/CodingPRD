"""Domain types for the Product Content Syndication & Digital Shelf API.

Entity TypedDicts, status enums and the role enum, all named exactly as the PRD
names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    SHELF_ADMIN = "ShelfAdmin"
    CONTENT_AUTHOR = "ContentAuthor"
    LEGAL_REVIEWER = "LegalReviewer"
    BRAND_GOVERNANCE_APPROVER = "BrandGovernanceApprover"
    SYNDICATION_OPERATOR = "SyndicationOperator"
    RETAILER_INTEGRATION = "RetailerIntegration"
    ACCOUNT_TEAM_LEAD = "AccountTeamLead"


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------
class RetailerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    OFFBOARDED = "OFFBOARDED"


class AttributeDataType(str, Enum):
    STRING = "STRING"
    INTEGER = "INTEGER"
    DECIMAL = "DECIMAL"
    ENUM = "ENUM"


class TaxonomyGroup(str, Enum):
    CORE = "CORE"
    MARKETING = "MARKETING"
    VARIANT = "VARIANT"
    COMPLIANCE = "COMPLIANCE"


class RequirementLevel(str, Enum):
    REQUIRED = "REQUIRED"
    RECOMMENDED = "RECOMMENDED"
    OPTIONAL = "OPTIONAL"


class ProductStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class GovernanceFlag(str, Enum):
    NONE = "NONE"
    CONTENT_AT_RISK = "CONTENT_AT_RISK"
    LISTING_RISK = "LISTING_RISK"


class ContentVersionState(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    PINNED = "PINNED"
    SUPERSEDED = "SUPERSEDED"


class AssetRole(str, Enum):
    HERO_IMAGE = "HERO_IMAGE"
    SECONDARY_IMAGE = "SECONDARY_IMAGE"
    VIDEO = "VIDEO"
    A_PLUS_MODULE = "A_PLUS_MODULE"


class ApprovalState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class MediaDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class SyndicationState(str, Enum):
    NOT_SYNDICATED = "NOT_SYNDICATED"
    PENDING = "PENDING"
    LIVE = "LIVE"
    ERROR_HOLD = "ERROR_HOLD"


class ShelfState(str, Enum):
    OK = "OK"
    OOS_WATCH = "OOS_WATCH"
    UNAUTHORIZED = "UNAUTHORIZED"
    SUSPENDED = "SUSPENDED"


class SyndicationJobState(str, Enum):
    QUEUED = "QUEUED"
    TRANSMITTED = "TRANSMITTED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"
    CANCELLED = "CANCELLED"


class FeedOutcome(str, Enum):
    ACCEPTED = "ACCEPTED"
    PARTIALLY_ACCEPTED = "PARTIALLY_ACCEPTED"
    REJECTED = "REJECTED"


class ErrorSeverity(str, Enum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"


class RejectionErrorState(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    WAIVED = "WAIVED"


class ResolutionMode(str, Enum):
    FIX = "FIX"
    WAIVE = "WAIVE"


class ChangeRequestState(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewTrackState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewTrack(str, Enum):
    LEGAL = "LEGAL"
    BRAND = "BRAND"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ModuleKind(str, Enum):
    A_PLUS_PAGE = "A_PLUS_PAGE"
    COMPARISON_CHART = "COMPARISON_CHART"
    VIDEO_BLOCK = "VIDEO_BLOCK"


class DeploymentState(str, Enum):
    PENDING_RETAILER_APPROVAL = "PENDING_RETAILER_APPROVAL"
    LIVE = "LIVE"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"


class AlertType(str, Enum):
    OUT_OF_STOCK = "OUT_OF_STOCK"
    UNAUTHORIZED_LISTING = "UNAUTHORIZED_LISTING"
    CONTENT_DRIFT = "CONTENT_DRIFT"
    HEALTH_DEGRADED = "HEALTH_DEGRADED"


class AlertSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class AlertState(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class LiftVariant(str, Enum):
    POST_PIN_WINDOW = "post_pin_window"
    QUALITY_SPLIT = "quality_split"


# --------------------------------------------------------------------------
# Entity shapes.  Every entity below carries id / created_at / updated_at /
# version except ShelfObservation, which the PRD declares append-only with
# only id and created_at.
# --------------------------------------------------------------------------
class Retailer(TypedDict):
    id: str
    name: str
    retailer_code: str
    status: str
    min_image_count: int
    feed_slot_capacity: int
    max_concurrent_feed_windows: int
    enhanced_content_requires_approval: bool
    feed_slots_reserved: int
    created_at: str
    updated_at: str
    version: int


class AttributeDefinition(TypedDict):
    id: str
    attribute_key: str
    data_type: str
    taxonomy_group: str
    max_chars: int
    base_weight: float
    is_global_required: bool
    created_at: str
    updated_at: str
    version: int


class RetailerRequirement(TypedDict):
    id: str
    retailer_id: str
    attribute_key: str
    requirement_level: str
    max_chars_override: Optional[int]
    weight_override: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    sku: str
    gtin: str
    category_code: str
    brand_code: str
    status: str
    shelf_health_index: float
    conversion_lift_pct: float
    open_alert_count: int
    governance_flag: str
    last_pinned_at: Optional[str]
    last_review_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContentVersion(TypedDict):
    id: str
    product_id: str
    supersedes_content_version_id: Optional[str]
    revision_no: int
    state: str
    image_count: int
    pin_count: int
    author_user_id: str
    created_at: str
    updated_at: str
    version: int


class ContentAttributeValue(TypedDict):
    id: str
    content_version_id: str
    attribute_key: str
    value: str
    char_count: int
    type_valid: bool
    created_at: str
    updated_at: str
    version: int


class MediaAsset(TypedDict):
    id: str
    product_id: str
    asset_role: str
    source_uri: str
    approval_state: str
    approving_retailer_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailerListing(TypedDict):
    id: str
    product_id: str
    retailer_id: str
    pinned_content_version_id: Optional[str]
    account_team_user_id: Optional[str]
    syndication_state: str
    shelf_state: str
    completeness_score_declared: float
    completeness_score_certified: float
    readiness_score: float
    search_rank_latest: Optional[int]
    content_accuracy_pct: Optional[float]
    rating_avg: Optional[float]
    in_stock: bool
    open_blocking_error_count: int
    created_at: str
    updated_at: str
    version: int


class SyndicationJob(TypedDict):
    id: str
    retailer_listing_id: str
    content_version_id: str
    slot_count: int
    window_start: str
    window_end: str
    state: str
    attempt_no: int
    readiness_at_queue: float
    service_fee_cents: int
    transmitted_at: Optional[str]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RejectionError(TypedDict):
    id: str
    syndication_job_id: str
    retailer_error_code: str
    attribute_key: Optional[str]
    severity: str
    message: str
    state: str
    resolution_mode: Optional[str]
    resolved_by_user_id: Optional[str]
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChangeRequest(TypedDict):
    id: str
    product_id: str
    retailer_id: str
    target_content_version_id: str
    rationale: str
    state: str
    legal_review_state: str
    brand_review_state: str
    author_user_id: str
    legal_reviewer_user_id: Optional[str]
    brand_reviewer_user_id: Optional[str]
    submitted_at: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnhancedContentDeployment(TypedDict):
    id: str
    retailer_listing_id: str
    change_request_id: str
    media_asset_id: str
    module_kind: str
    window_start: str
    window_end: str
    state: str
    retailer_decision_at: Optional[str]
    withdrawn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShelfObservation(TypedDict):
    """Append-only event row: only id and created_at, no updated_at, no version."""
    id: str
    created_at: str
    retailer_listing_id: str
    observed_at: str
    search_rank: Optional[int]
    in_stock: bool
    content_accuracy_pct: float
    rating_avg: float
    rating_count: int
    unauthorized_seller_count: int
    conversion_rate_pct: float
    units_sold: int


class ShelfAlert(TypedDict):
    id: str
    retailer_listing_id: str
    source_observation_id: Optional[str]
    alert_type: str
    severity: str
    state: str
    assigned_account_team_user_id: Optional[str]
    acknowledged_by_user_id: Optional[str]
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompletenessDiagnostic(TypedDict):
    retailer_listing_id: str
    declared_score: float
    certified_score: float
    declared_source_content_version_id: Optional[str]
    certified_source_content_version_id: Optional[str]
    requirement_weight_total: float
    declared_image_component: float
    certified_image_component: float
    missing_required_keys: List[str]
    over_limit_keys: List[str]


class ShelfSummary(TypedDict):
    product_id: str
    shelf_health_index: float
    qualifying_listing_count: int
    retailer_subscores: list
    conversion_lift_pct: float
    lift_variant: str
    high_group_size: int
    base_group_size: int
