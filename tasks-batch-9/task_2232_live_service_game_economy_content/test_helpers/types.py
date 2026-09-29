"""Domain types for the live-service economy API: status enums, role enum, entity TypedDicts."""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CONTENT_PRODUCER = "ContentProducer"
    ECONOMY_DESIGNER = "EconomyDesigner"
    LIVE_OPS_COMMANDER = "LiveOpsCommander"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLAYER = "Player"


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------
class SeasonStatus(str, Enum):
    PLANNED = "PLANNED"
    LIVE = "LIVE"
    CONCLUDED = "CONCLUDED"
    ARCHIVED = "ARCHIVED"


class EconomyHealth(str, Enum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    INFLATED = "INFLATED"


class ContentPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    BEHIND = "BEHIND"


class EpisodeStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    LIVE = "LIVE"
    CONCLUDED = "CONCLUDED"
    ROLLED_BACK = "ROLLED_BACK"


class ClusterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DRAINING = "DRAINING"
    RETIRED = "RETIRED"


class RegionCode(str, Enum):
    NA = "NA"
    EU = "EU"
    LATAM = "LATAM"
    APAC = "APAC"


class LiveEventStatus(str, Enum):
    PLANNED = "PLANNED"
    APPROVED = "APPROVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ROLLED_BACK = "ROLLED_BACK"
    CANCELLED = "CANCELLED"


class SpendState(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    COOLDOWN = "COOLDOWN"
    LOCKED = "LOCKED"


class RetentionBand(str, Enum):
    HEALTHY = "HEALTHY"
    AT_RISK = "AT_RISK"
    CHURN_RISK = "CHURN_RISK"


class CurrencyCode(str, Enum):
    HARD_GEM = "HARD_GEM"
    SOFT_COIN = "SOFT_COIN"
    EVENT_TOKEN = "EVENT_TOKEN"


class CurrencyAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"


class LedgerDirection(str, Enum):
    FAUCET = "FAUCET"
    SINK = "SINK"


class LedgerSourceKind(str, Enum):
    EPISODE_GRANT = "EPISODE_GRANT"
    PURCHASE_GRANT = "PURCHASE_GRANT"
    OFFER_SPEND = "OFFER_SPEND"
    EVENT_REWARD = "EVENT_REWARD"
    ADMIN_ADJUSTMENT = "ADMIN_ADJUSTMENT"
    REFUND_REVERSAL = "REFUND_REVERSAL"
    EPISODE_ROLLBACK_REVERSAL = "EPISODE_ROLLBACK_REVERSAL"


class OfferType(str, Enum):
    BATTLE_PASS = "BATTLE_PASS"
    BUNDLE = "BUNDLE"
    LIMITED_TIME = "LIMITED_TIME"
    LOOT_BOX = "LOOT_BOX"


class PriceTier(str, Enum):
    T1 = "T1"
    T2 = "T2"
    T3 = "T3"
    T4 = "T4"


class OfferApprovalStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"


class OfferAvailabilityStatus(str, Enum):
    OFFLINE = "OFFLINE"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class DisclosureState(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED_MISSING = "REQUIRED_MISSING"
    PUBLISHED = "PUBLISHED"


class ProbabilityDisclosureStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class PurchaseStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    DENIED = "DENIED"
    REFUNDED = "REFUNDED"


class RefundReasonCode(str, Enum):
    ACCIDENTAL = "ACCIDENTAL"
    MINOR_UNAUTHORIZED = "MINOR_UNAUTHORIZED"
    DISSATISFIED = "DISSATISFIED"
    TECHNICAL_FAILURE = "TECHNICAL_FAILURE"


class RefundRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXECUTED = "EXECUTED"


class BalanceChangeTargetKind(str, Enum):
    SINK_RATE = "SINK_RATE"
    FAUCET_RATE = "FAUCET_RATE"
    DROP_RATE = "DROP_RATE"
    PRICE = "PRICE"


class BalanceChangeStage(str, Enum):
    DRAFT = "DRAFT"
    SHADOW = "SHADOW"
    CANARY = "CANARY"
    LIVE = "LIVE"
    REVERTED = "REVERTED"
    RETIRED = "RETIRED"


class CommsState(str, Enum):
    MISSING = "MISSING"
    DRAFTED = "DRAFTED"
    PUBLISHED = "PUBLISHED"


class CommsChannel(str, Enum):
    PATCH_NOTES = "PATCH_NOTES"
    IN_GAME = "IN_GAME"
    SOCIAL = "SOCIAL"


class CommsNoticeStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class MonitoringRunStatus(str, Enum):
    OPEN = "OPEN"
    COMPUTED = "COMPUTED"
    CERTIFIED = "CERTIFIED"
    VOIDED = "VOIDED"


class RatioVariant(str, Enum):
    EPOCH_WINDOWED = "EPOCH_WINDOWED"
    LIFETIME_CUMULATIVE = "LIFETIME_CUMULATIVE"


class PacingVariant(str, Enum):
    REALIZED = "REALIZED"
    PROJECTED = "PROJECTED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------
class Season(TypedDict):
    id: str
    code: str
    title: str
    starts_at: str
    ends_at: str
    planned_episode_count: int
    target_xp_total: int
    pass_price_minor: int
    status: str
    economy_health: str
    content_posture: str
    scheduled_episode_count: int
    released_episode_count: int
    cadence_debt_days: int
    gross_faucet_minor: int
    gross_sink_minor: int
    lifetime_ratio_bp: int
    pending_revenue_minor: int
    settled_revenue_minor: int
    live_offer_count: int
    effective_sink_rate_bp: int
    active_tuning_count: int
    tuning_stage_epoch: int
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict):
    id: str
    season_id: str
    sequence_no: int
    title: str
    planned_release_at: str
    actual_release_at: Optional[str]
    xp_grant: int
    soft_currency_grant_minor: int
    status: str
    rollback_count: int
    grant_batch_size: int
    created_at: str
    updated_at: str
    version: int


class CapacityCluster(TypedDict):
    id: str
    name: str
    region_code: str
    ccu_capacity: int
    maintenance_buffer_minutes: int
    status: str
    reserved_ccu: int
    created_at: str
    updated_at: str
    version: int


class LiveEvent(TypedDict):
    id: str
    season_id: str
    capacity_cluster_id: str
    code: str
    window_start: str
    window_end: str
    forecast_ccu: int
    status: str
    reserved_ccu_at_approval: int
    rollback_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Player(TypedDict):
    id: str
    handle: str
    region_code: str
    active_season_id: str
    is_minor: bool
    guardian_verified: bool
    spend_state: str
    season_xp_total: int
    session_count: int
    last_active_at: Optional[str]
    pacing_bp_realized: int
    retention_band: str
    spend_30d_minor: int
    pending_spend_minor: int
    lifetime_spend_minor: int
    created_at: str
    updated_at: str
    version: int


class CurrencyAccount(TypedDict):
    id: str
    player_id: str
    currency_code: str
    balance_minor: int
    lifetime_faucet_minor: int
    lifetime_sink_minor: int
    status: str
    created_at: str
    updated_at: str
    version: int


class EconomyLedgerEntry(TypedDict):
    """Append-only ledger row: it exposes only id and created_at as common fields —
    no updated_at and no version."""

    id: str
    currency_account_id: str
    season_id: str
    purchase_id: Optional[str]
    direction: str
    amount_minor: int
    source_kind: str
    occurred_at: str
    reversal_of_entry_id: Optional[str]
    created_at: str


class OfferLineItem(TypedDict):
    sku: str
    base_price_minor: int
    declared_value_minor: int
    granted_currency_code: str
    granted_amount_minor: int


class Offer(TypedDict):
    id: str
    season_id: str
    offer_type: str
    sku: str
    price_tier: str
    list_price_minor: int
    line_items: List[OfferLineItem]
    personalization_discount_bp: int
    minor_purchasable: bool
    window_start: str
    window_end: str
    approval_status: str
    availability_status: str
    fairness_index_bp: int
    disclosure_state: str
    units_sold: int
    pending_purchase_count: int
    created_by_user_id: str
    reviewed_by_user_id: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class DisclosureEntry(TypedDict):
    item_sku: str
    probability_bp: int
    item_value_minor: int
    is_rare: bool


class ProbabilityDisclosure(TypedDict):
    id: str
    offer_id: str
    entries: List[DisclosureEntry]
    total_probability_bp: int
    expected_value_minor: int
    status: str
    published_at: Optional[str]
    published_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Purchase(TypedDict):
    id: str
    player_id: str
    offer_id: str
    quoted_price_minor: int
    applied_personalization_bp: int
    price_paid_minor: int
    granted_total_minor: int
    granted_consumed_minor: int
    is_minor_purchase: bool
    status: str
    settled_at: Optional[str]
    deny_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RefundRequest(TypedDict):
    id: str
    purchase_id: str
    reason_code: str
    status: str
    consumed_ratio_bp: int
    refund_base_minor: int
    restock_fee_minor: int
    refund_amount_minor: int
    goodwill_credit_minor: int
    decision_note: Optional[str]
    decided_by_user_id: Optional[str]
    executed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BalanceChange(TypedDict):
    id: str
    season_id: str
    target_kind: str
    delta_bp: int
    rationale: str
    canary_cohort_pct: int
    stage: str
    comms_state: str
    authored_by_user_id: str
    promoted_by_user_id: Optional[str]
    pre_live_sink_rate_bp: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CommsNotice(TypedDict):
    id: str
    balance_change_id: str
    channel: str
    headline: str
    body: str
    status: str
    published_at: Optional[str]
    published_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonitoringRun(TypedDict):
    id: str
    season_id: str
    epoch_no: int
    window_start: str
    window_end: str
    gross_faucet_minor: int
    gross_sink_minor: int
    sink_faucet_ratio_bp: Optional[int]
    resulting_health: Optional[str]
    suspended_offer_count: int
    denied_purchase_count: int
    status: str
    computed_at: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QuoteResult(TypedDict):
    offer_id: str
    player_id: str
    region_multiplier_bp: int
    tier_discount_bp: int
    applied_personalization_bp: int
    retention_band: str
    quote_minor: int
    line_breakdown: List[Dict[str, Any]]


class PacingResult(TypedDict):
    player_id: str
    variant: str
    elapsed_days: int
    season_total_days: int
    expected_to_date_xp: int
    eligible_scheduled_xp: int
    season_xp_total: int
    pacing_bp: int
    retention_band: str


class EconomySummary(TypedDict):
    season_id: str
    variant: str
    window_start: str
    window_end: str
    gross_faucet_minor: int
    gross_sink_minor: int
    sink_faucet_ratio_bp: int
    health_band: str
    economy_health: str
    cadence_debt_days: int
    content_posture: str
    effective_sink_rate_bp: int
