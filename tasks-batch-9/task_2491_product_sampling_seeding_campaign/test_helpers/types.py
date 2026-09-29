"""Domain types for the Product Sampling & Seeding API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CAMPAIGN_MANAGER = "CampaignManager"
    COMPLIANCE_MODERATOR = "ComplianceModerator"
    FULFILLMENT_OPS = "FulfillmentOps"
    PANELIST = "Panelist"
    PLATFORM_ADMIN = "PlatformAdmin"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------
class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENING_OPEN = "SCREENING_OPEN"
    SAMPLING_ACTIVE = "SAMPLING_ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVIEW_WINDOW = "REVIEW_WINDOW"
    CLOSED = "CLOSED"


class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class ObjectiveType(str, Enum):
    TRIAL_GENERATION = "TRIAL_GENERATION"
    REVIEW_ACQUISITION = "REVIEW_ACQUISITION"
    AWARENESS = "AWARENESS"


class KitLineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class ComponentRole(str, Enum):
    HERO_PRODUCT = "HERO_PRODUCT"
    ACCESSORY = "ACCESSORY"
    INSERT_CARD = "INSERT_CARD"
    DISCLOSURE_INSERT = "DISCLOSURE_INSERT"


class FulfillmentWaveStatus(str, Enum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"


class PanelistIntegrityStatus(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    BANNED = "BANNED"


class RiskScoreVariant(str, Enum):
    SCREENING = "SCREENING"
    AUDIT = "AUDIT"


class ScreeningStatus(str, Enum):
    PENDING_SCREEN = "PENDING_SCREEN"
    SCREEN_PASSED = "SCREEN_PASSED"
    SCREEN_FAILED = "SCREEN_FAILED"
    SCREEN_REVOKED = "SCREEN_REVOKED"


class ObligationStatus(str, Enum):
    NONE = "NONE"
    SAMPLE_SENT = "SAMPLE_SENT"
    REVIEW_DUE = "REVIEW_DUE"
    REVIEW_FULFILLED = "REVIEW_FULFILLED"
    FORFEITED = "FORFEITED"


class ScreeningFailureReason(str, Enum):
    SEGMENT_MISMATCH = "SEGMENT_MISMATCH"
    FRAUD_SCORE_TOO_HIGH = "FRAUD_SCORE_TOO_HIGH"
    COOLDOWN_CONFLICT = "COOLDOWN_CONFLICT"
    INTEGRITY_HOLD = "INTEGRITY_HOLD"


class SampleShipmentStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    LOST = "LOST"
    CANCELLED = "CANCELLED"


class ReviewSubmissionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    DISCLOSURE_REJECTED = "DISCLOSURE_REJECTED"
    APPROVED = "APPROVED"
    RETRACTED = "RETRACTED"


class ModerationDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT_DISCLOSURE = "REJECT_DISCLOSURE"


class RetailerFeedStatus(str, Enum):
    ACCEPTING = "ACCEPTING"
    PAUSED = "PAUSED"


class SyndicationRecordStatus(str, Enum):
    QUEUED = "QUEUED"
    SYNDICATED = "SYNDICATED"
    REJECTED = "REJECTED"
    TAKEDOWN_REQUESTED = "TAKEDOWN_REQUESTED"


class SyndicationRejectionReason(str, Enum):
    BELOW_MIN_RATING = "BELOW_MIN_RATING"
    DISCLOSURE_BADGE_MISSING = "DISCLOSURE_BADGE_MISSING"
    PANELIST_RATE_LIMIT = "PANELIST_RATE_LIMIT"


class DiversionCaseStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class DiversionSignalType(str, Enum):
    RESALE_LISTING = "RESALE_LISTING"
    ADDRESS_CLUSTER = "ADDRESS_CLUSTER"
    BULK_REDEMPTION = "BULK_REDEMPTION"


class LiftVariant(str, Enum):
    ITT = "ITT"
    PER_PROTOCOL = "PER_PROTOCOL"


class PowerStatus(str, Enum):
    MEASURED = "MEASURED"
    INSUFFICIENT_POWER = "INSUFFICIENT_POWER"


# ---------------------------------------------------------------------------
# Entity shapes.  Every entity below carries id / created_at / updated_at /
# version except PurchaseMatch, which is immutable once ingested and therefore
# carries only id and created_at (PRD §2.4).
# ---------------------------------------------------------------------------
class Campaign(TypedDict):
    id: str
    name: str
    objective_type: str
    target_segment_codes: List[str]
    syndication_retailer_ids: List[str]
    sampling_window_start: str
    sampling_window_end: str
    review_due_days: int
    min_review_word_count: int
    holdout_pct: float
    budget_total_cents: int
    status: str
    compliance_posture: str
    kit_assembly_unit_cost_cents: int
    budget_committed_cents: int
    budget_available_cents: int
    enrollment_count: int
    holdout_enrollment_count: int
    allocated_sample_count: int
    delivered_sample_count: int
    approved_review_count: int
    syndicated_review_count: int
    disclosure_rejected_review_count: int
    substantiated_diversion_count: int
    write_off_cost_cents: int
    cost_per_sample_provisional_cents: int
    cost_per_sample_final_cents: int
    launched_by_user_id: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KitLine(TypedDict):
    id: str
    campaign_id: str
    component_sku: str
    component_role: str
    unit_cost_cents: int
    quantity_per_kit: int
    component_discount_pct: float
    extended_cost_cents: int
    status: str
    units_received: int
    units_available: int
    units_reserved: int
    units_shipped: int
    units_written_off: int
    created_at: str
    updated_at: str
    version: int


class FulfillmentCenter(TypedDict):
    id: str
    name: str
    zone_code: str
    daily_pick_capacity_units: int
    freight_cents_per_kit: int
    created_at: str
    updated_at: str
    version: int


class FulfillmentWave(TypedDict):
    id: str
    fulfillment_center_id: str
    window_start: str
    window_end: str
    planned_capacity_units: int
    planned_unit_count: int
    shipped_unit_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Panelist(TypedDict):
    id: str
    email: str
    display_name: str
    address_hash: str
    account_opened_at: str
    segment_code: str
    referred_by_panelist_id: Optional[str]
    integrity_status: str
    diversion_strikes: int
    fraud_risk_score_screening: float
    fraud_risk_score_audit: Optional[float]
    last_risk_scored_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    campaign_id: str
    panelist_id: str
    screening_answers: Dict[str, Any]
    enrollment_seq: int
    holdout_flag: bool
    screening_status: str
    obligation_status: str
    screening_failure_reason: Optional[str]
    screen_attempt_count: int
    review_due_at: Optional[str]
    fraud_score_at_screening: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SampleShipment(TypedDict):
    id: str
    enrollment_id: str
    fulfillment_wave_id: str
    supersedes_shipment_id: Optional[str]
    surcharge_cents: int
    status: str
    committed_cost_cents: int
    reserved_line_units: Dict[str, int]
    kit_unit_total: int
    shipped_at: Optional[str]
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewSubmission(TypedDict):
    id: str
    enrollment_id: str
    headline: str
    body_text: str
    star_rating: int
    disclosure_statement: Optional[str]
    honest_opinion_attested: bool
    word_count: int
    status: str
    revision_count: int
    first_submitted_at: Optional[str]
    changes_requested_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    moderator_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Retailer(TypedDict):
    id: str
    name: str
    feed_status: str
    requires_disclosure_badge: bool
    min_star_rating_accepted: int
    max_reviews_per_panelist_per_month: int
    created_at: str
    updated_at: str
    version: int


class SyndicationRecord(TypedDict):
    id: str
    review_submission_id: str
    retailer_id: str
    status: str
    rejection_reason: Optional[str]
    syndicated_at: Optional[str]
    takedown_requested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiversionCase(TypedDict):
    id: str
    panelist_id: str
    sample_shipment_id: str
    signal_type: str
    evidence_note: str
    status: str
    opened_by_user_id: str
    substantiated_at: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class PurchaseMatch(TypedDict):
    """Immutable once ingested — carries only id and created_at (PRD §2.4)."""

    id: str
    enrollment_id: str
    retailer_channel_code: str
    purchase_amount_cents: int
    purchased_at: str
    match_confidence: float
    qualified: bool
    created_at: str


class LiftAnalysis(TypedDict):
    id: str
    campaign_id: str
    variant: str
    treated_count: int
    holdout_count: int
    treated_converted_count: int
    holdout_converted_count: int
    treated_conversion_rate: float
    holdout_conversion_rate: float
    lift_pct: float
    power_status: str
    effective_sample_count: int
    diverted_unit_count: int
    base_cost_per_sample_cents: int
    penalty_rate_pct: int
    diversion_penalty_cents: int
    adjusted_cost_per_sample_cents: int
    superseded: bool
    computed_at: str
    created_at: str
    updated_at: str
    version: int
