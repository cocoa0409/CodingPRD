"""Domain types for the Brand Safety & Ad Verification Operations API.

Entity TypedDicts, status enums and the caller-role enum, all named exactly as
the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD 2.1 - the seven declared roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ADVERTISER = "Advertiser"
    PUBLISHER = "Publisher"
    CLASSIFICATION_ANALYST = "ClassificationAnalyst"
    DISPUTE_OFFICER = "DisputeOfficer"
    ACCREDITATION_AUDITOR = "AccreditationAuditor"
    MEASUREMENT_OPERATOR = "MeasurementOperator"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Shared vocabularies (PRD 2.5)
# ---------------------------------------------------------------------------
class SuitabilityTier(str, Enum):
    FLOOR = "FLOOR"
    HIGH_RISK = "HIGH_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    LOW_RISK = "LOW_RISK"
    SAFE = "SAFE"


class AssessedTier(str, Enum):
    """Post-bid tiers add UNRATED for a page with no classification."""
    FLOOR = "FLOOR"
    HIGH_RISK = "HIGH_RISK"
    MEDIUM_RISK = "MEDIUM_RISK"
    LOW_RISK = "LOW_RISK"
    SAFE = "SAFE"
    UNRATED = "UNRATED"


class CreativeFormat(str, Enum):
    DISPLAY = "DISPLAY"
    LARGE_DISPLAY = "LARGE_DISPLAY"
    VIDEO = "VIDEO"


CATEGORY_CODES = [
    "ADULT", "TERRORISM", "ILLEGAL_DRUGS", "ARMS", "CRIME_VIOLENCE",
    "HATE_SPEECH", "PIRACY", "DEATH_INJURY", "TOBACCO_ALCOHOL", "GAMBLING",
    "DEBATED_SOCIAL", "NEWS_HARD", "SPORTS_NEWS", "GENERAL",
]


# ---------------------------------------------------------------------------
# Status enums, one per state field
# ---------------------------------------------------------------------------
class PublisherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"
    DELISTED = "DELISTED"


class PublisherStatusReason(str, Enum):
    QUARANTINE_THRESHOLD = "QUARANTINE_THRESHOLD"
    MFA_THRESHOLD = "MFA_THRESHOLD"
    ADMIN_ACTION = "ADMIN_ACTION"
    ADMIN_REINSTATEMENT = "ADMIN_REINSTATEMENT"


class StandardFamily(str, Enum):
    VIEWABILITY = "VIEWABILITY"
    IVT = "IVT"
    SUITABILITY = "SUITABILITY"


class AccreditationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACCREDITED = "ACCREDITED"
    SUSPENDED = "SUSPENDED"
    LAPSED = "LAPSED"


class AuditOutcome(str, Enum):
    PASSED = "PASSED"
    DEFICIENT = "DEFICIENT"


class CampaignStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REMEDIATION = "UNDER_REMEDIATION"


class CoverageStatus(str, Enum):
    UNKNOWN = "UNKNOWN"
    ON_TARGET = "ON_TARGET"
    BELOW_TARGET = "BELOW_TARGET"


class ListType(str, Enum):
    INCLUSION = "INCLUSION"
    EXCLUSION = "EXCLUSION"


class ListStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    STALE = "STALE"


class EntryType(str, Enum):
    PAGE_URL = "PAGE_URL"
    DOMAIN = "DOMAIN"
    PUBLISHER = "PUBLISHER"
    CATEGORY = "CATEGORY"


class EntryAction(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


class SyncStatus(str, Enum):
    PENDING = "PENDING"
    SYNCED = "SYNCED"
    STALE = "STALE"


class SegmentStaleReason(str, Enum):
    LIST_STALE = "LIST_STALE"
    CAMPAIGN_UNDER_REMEDIATION = "CAMPAIGN_UNDER_REMEDIATION"


LIST_STALE_REASON_RESTRICTED_PUBLISHER_ENTRY = "RESTRICTED_PUBLISHER_ENTRY"


class ClassificationState(str, Enum):
    UNCLASSIFIED = "UNCLASSIFIED"
    MODEL_CLASSIFIED = "MODEL_CLASSIFIED"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    APPEALED = "APPEALED"
    RECLASSIFIED = "RECLASSIFIED"


class ClassifierKind(str, Enum):
    MODEL = "MODEL"
    HUMAN = "HUMAN"
    APPEAL_REMEDY = "APPEAL_REMEDY"


class ReviewState(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    CONFIRMED = "CONFIRMED"
    OVERRIDDEN = "OVERRIDDEN"
    SUPERSEDED = "SUPERSEDED"
    VACATED = "VACATED"


class ReviewDecision(str, Enum):
    CONFIRM = "CONFIRM"
    OVERRIDE = "OVERRIDE"


class AppealState(str, Enum):
    FILED = "FILED"
    MORE_EVIDENCE_REQUIRED = "MORE_EVIDENCE_REQUIRED"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class AppealReasonCode(str, Enum):
    CATEGORY_MISREAD = "CATEGORY_MISREAD"
    CONTEXT_IGNORED = "CONTEXT_IGNORED"
    STALE_CRAWL = "STALE_CRAWL"
    MFA_SIGNAL_WRONG = "MFA_SIGNAL_WRONG"


class AppealOutcome(str, Enum):
    MORE_EVIDENCE = "MORE_EVIDENCE"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class ScoringStatus(str, Enum):
    INGESTED = "INGESTED"
    SCORED = "SCORED"
    CERTIFIED = "CERTIFIED"
    QUARANTINED = "QUARANTINED"
    DECERTIFIED = "DECERTIFIED"


class SettlementStatus(str, Enum):
    UNBILLED = "UNBILLED"
    CLAIMED = "CLAIMED"
    CREDITED = "CREDITED"
    CLOSED_NO_CREDIT = "CLOSED_NO_CREDIT"


class IvtClass(str, Enum):
    GENERAL_BOT = "GENERAL_BOT"
    DATACENTER = "DATACENTER"
    SIVT_HIJACKED_DEVICE = "SIVT_HIJACKED_DEVICE"
    SIVT_AD_FARM = "SIVT_AD_FARM"
    SIVT_INCENTIVIZED = "SIVT_INCENTIVIZED"


class IvtFamily(str, Enum):
    GIVT = "GIVT"
    SIVT = "SIVT"


class FindingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    RETRACTED = "RETRACTED"


class ClaimState(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    REVERSED = "REVERSED"


class RejectReasonCode(str, Enum):
    EVIDENCE_INSUFFICIENT = "EVIDENCE_INSUFFICIENT"
    BATCH_RESCORED = "BATCH_RESCORED"
    DUPLICATE_CLAIM = "DUPLICATE_CLAIM"
    APPEAL_OVERTURNED = "APPEAL_OVERTURNED"


class TierBand(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    WATCHLIST = "WATCHLIST"
    SUSPENDED_QUALITY = "SUSPENDED_QUALITY"


class PreBidDecision(str, Enum):
    ALLOW = "ALLOW"
    ALLOW_OVERRIDE = "ALLOW_OVERRIDE"
    BLOCK = "BLOCK"


class PreBidReasonCode(str, Enum):
    PUBLISHER_RESTRICTED = "PUBLISHER_RESTRICTED"
    LIST_EXCLUSION = "LIST_EXCLUSION"
    LIST_INCLUSION = "LIST_INCLUSION"
    UNRATED_INVENTORY = "UNRATED_INVENTORY"
    BELOW_SUITABILITY_FLOOR = "BELOW_SUITABILITY_FLOOR"
    MEETS_FLOOR = "MEETS_FLOOR"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Resources carrying id + created_at + updated_at + version, except ListEntry
# which the PRD declares append-only and immutable (id + created_at only).
# ---------------------------------------------------------------------------
class Advertiser(TypedDict):
    id: str
    name: str
    credit_cap_cents: int
    credit_received_cents_total: int
    settled_claim_count: int
    created_at: str
    updated_at: str
    version: int


class Publisher(TypedDict):
    id: str
    name: str
    primary_domain: str
    sourced_traffic_pct: float
    publisher_status: str
    status_reason: Optional[str]
    mfa_page_count: int
    quarantined_batch_count: int
    certified_batch_count: int
    decided_appeal_count: int
    overturned_appeal_count: int
    credit_issued_cents_total: int
    created_at: str
    updated_at: str
    version: int


class MethodologyVersion(TypedDict):
    id: str
    standard_family: str
    version_code: str
    effective_from: str
    effective_to: str
    display_in_view_seconds: float
    video_in_view_seconds: float
    display_pixel_pct: float
    large_display_pixel_pct: float
    video_pixel_pct: float
    coverage_rate_floor: float
    ivt_rate_ceiling: float
    accreditation_status: str
    authored_by_user_id: str
    lead_auditor_user_id: Optional[str]
    audit_outcome: Optional[str]
    audit_finding_rate: Optional[float]
    deficiency_note: Optional[str]
    decertified_batch_count: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    advertiser_id: str
    name: str
    cpm_cents: int
    min_suitability_tier: str
    target_coverage_rate: float
    format: str
    status: str
    coverage_status: str
    certified_measured_impressions: int
    certified_measurable_impressions: int
    open_claim_count: int
    created_at: str
    updated_at: str
    version: int


class InventoryList(TypedDict):
    id: str
    advertiser_id: str
    list_type: str
    name: str
    status: str
    entry_count: int
    published_version: Optional[int]
    published_at: Optional[str]
    stale_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ListEntry(TypedDict):
    """Append-only and immutable: carries only id and created_at."""
    id: str
    list_id: str
    entry_type: str
    entry_value: str
    action: str
    specificity_rank: int
    created_at: str


class PreBidSegment(TypedDict):
    id: str
    campaign_id: str
    inclusion_list_id: Optional[str]
    exclusion_list_id: Optional[str]
    suitability_floor_tier: str
    sync_status: str
    synced_inclusion_version: Optional[int]
    synced_exclusion_version: Optional[int]
    synced_at: Optional[str]
    stale_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Page(TypedDict):
    id: str
    publisher_id: str
    url: str
    domain: str
    classification_state: str
    current_tier: Optional[str]
    current_classification_id: Optional[str]
    latest_category_codes: List[str]
    mfa_score: Optional[float]
    mfa_flag: bool
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class PageClassification(TypedDict):
    id: str
    page_id: str
    methodology_version_id: str
    classifier_kind: str
    category_codes: List[str]
    model_confidence: float
    ad_density_ratio: float
    refresh_seconds: int
    originality_score: float
    base_risk_points: float
    adjusted_risk_points: float
    assigned_tier: str
    mfa_score: float
    mfa_flag: bool
    review_state: str
    classifier_user_id: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    classification_id: str
    reason_code: str
    evidence_note: str
    appeal_state: str
    round_no: int
    revised_tier: Optional[str]
    decision_note: Optional[str]
    decided_by_user_id: Optional[str]
    remedy_classification_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MeasurementBatch(TypedDict):
    id: str
    campaign_id: str
    publisher_id: str
    page_id: str
    methodology_version_id: str
    format: str
    window_start: str
    window_end: str
    measured_impressions: int
    measurable_impressions: int
    in_view_impressions: int
    avg_in_view_seconds: float
    avg_in_view_pixel_pct: float
    qualified_in_view_impressions: int
    non_viewable_impressions: int
    unmeasurable_impressions: int
    coverage_rate: Optional[float]
    viewability_rate: Optional[float]
    ivt_impressions: int
    ivt_rate: float
    sophistication_flag: bool
    net_billable_impressions: int
    assessed_tier: Optional[str]
    suitability_breach_flag: bool
    scoring_status: str
    settlement_status: str
    scored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IvtFinding(TypedDict):
    id: str
    batch_id: str
    ivt_class: str
    ivt_family: str
    flagged_impressions: int
    confidence: float
    detector_note: Optional[str]
    status: str
    retract_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundClaim(TypedDict):
    id: str
    campaign_id: str
    publisher_id: str
    batch_ids: List[str]
    claim_state: str
    claimed_impressions: int
    provisional_credit_cents: int
    credited_impressions: Optional[int]
    gross_credit_cents: Optional[int]
    admin_fee_rate: Optional[float]
    admin_fee_cents: Optional[int]
    net_credit_cents: Optional[int]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    reject_reason_code: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PublisherScorecard(TypedDict):
    publisher_id: str
    adjudicated_batch_count: int
    ivt_rate_avg: float
    viewability_rate_avg: float
    overturn_rate: float
    mfa_page_count: int
    quarantined_batch_count: int
    quality_index: float
    tier_band: str


class PreBidDecisionResult(TypedDict):
    page_id: str
    segment_id: str
    decision: str
    reason_code: str
    decisive_entry_id: Optional[str]
    decisive_specificity: Optional[str]
    effective_tier: str
    floor_tier: str
