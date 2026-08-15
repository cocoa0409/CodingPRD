"""Domain types: entity TypedDicts, status enums, role enum.

Common-field branching: every entity except RevenueReport carries
id + created_at + updated_at + version. RevenueReport is append-only
(common_fields false): only id + created_at; updated_at and version are
absent from it.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class ArtistStatus(str, Enum):
    SCOUTED = "SCOUTED"
    IN_NEGOTIATION = "IN_NEGOTIATION"
    SIGNED = "SIGNED"
    ACTIVE = "ACTIVE"
    HIATUS = "HIATUS"
    DROPPED = "DROPPED"


class DealMemoStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OPTION_WINDOW = "OPTION_WINDOW"
    EXTENDED = "EXTENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AdvanceStatus(str, Enum):
    PENDING = "PENDING"
    FUNDED = "FUNDED"


class PayoutStatus(str, Enum):
    RECOUPING = "RECOUPING"
    EARNING = "EARNING"


class ProjectStatus(str, Enum):
    PLANNED = "PLANNED"
    RECORDING = "RECORDING"
    POST_PRODUCTION = "POST_PRODUCTION"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class BudgetPosture(str, Enum):
    WITHIN_BUDGET = "WITHIN_BUDGET"
    AT_RISK = "AT_RISK"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class TrackStatus(str, Enum):
    DEMO = "DEMO"
    TRACKED = "TRACKED"
    MIXED = "MIXED"
    MASTERED = "MASTERED"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class AssetStatus(str, Enum):
    DRAFT = "DRAFT"
    ASSEMBLED = "ASSEMBLED"
    LOCKED = "LOCKED"


class DistributionStatus(str, Enum):
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    LIVE = "LIVE"
    TAKEN_DOWN = "TAKEN_DOWN"
    CANCELLED = "CANCELLED"


class DeliveryStatus(str, Enum):
    QUEUED = "QUEUED"
    TRANSMITTED = "TRANSMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class BeatStatus(str, Enum):
    PLANNED = "PLANNED"
    READY = "READY"
    EXECUTED = "EXECUTED"
    MEASURED = "MEASURED"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


class CampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    COMPLETED = "COMPLETED"
    KILLED = "KILLED"


class TourSupportStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    ADVANCED = "ADVANCED"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class TourExpenseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class RoyaltyRunStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    CALCULATED = "CALCULATED"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class StatementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    DISPUTED = "DISPUTED"
    PAID = "PAID"


class Genre(str, Enum):
    POP = "POP"
    HIPHOP = "HIPHOP"
    ROCK = "ROCK"
    ELECTRONIC = "ELECTRONIC"
    OTHER = "OTHER"


class RecoupmentScope(str, Enum):
    MASTER_ONLY = "MASTER_ONLY"
    CROSS_COLLATERALIZED = "CROSS_COLLATERALIZED"


class ChannelType(str, Enum):
    DSP = "DSP"
    PHYSICAL = "PHYSICAL"
    RADIO = "RADIO"


class RevenueChannel(str, Enum):
    STREAMING = "STREAMING"
    DOWNLOAD = "DOWNLOAD"
    PHYSICAL = "PHYSICAL"
    SYNC = "SYNC"


class BeatChannel(str, Enum):
    PLAYLIST = "PLAYLIST"
    RADIO = "RADIO"
    SOCIAL = "SOCIAL"
    PRESS = "PRESS"


class PromoChannel(str, Enum):
    PLAYLIST = "PLAYLIST"
    RADIO = "RADIO"


class TourExpenseCategory(str, Enum):
    TRAVEL = "TRAVEL"
    LODGING = "LODGING"
    PRODUCTION = "PRODUCTION"
    MISC = "MISC"


class ProjectType(str, Enum):
    SINGLE = "SINGLE"
    EP = "EP"
    ALBUM = "ALBUM"


class ReleaseType(str, Enum):
    SINGLE = "SINGLE"
    ALBUM = "ALBUM"


class UserRole(str, Enum):
    LABEL_ADMIN = "LabelAdmin"
    ANR_MANAGER = "AnRManager"
    FINANCE_CONTROLLER = "FinanceController"
    MARKETING_MANAGER = "MarketingManager"
    ARTIST_PORTAL = "ArtistPortal"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true
# ---------------------------------------------------------------------------


class Label(TypedDict):
    id: str
    name: str
    advance_cap_cents: int
    reserve_rate_bps: int
    sign_threshold_score: float
    option_window_days: int
    release_lead_days: int
    beat_pre_release_days: int
    beat_post_release_days: int
    campaign_gap_days: int
    genre_multipliers: Dict[str, float]
    channel_deduction_bps: Dict[str, int]
    tier_thresholds: List[Dict[str, int]]
    tour_category_caps_bps: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class Artist(TypedDict):
    id: str
    label_id: str
    stage_name: str
    genre: str
    birth_date: str
    monthly_streams: int
    social_followers: int
    engagement_rate: float
    live_draw_avg: int
    scouting_score: float
    status: str
    pre_hiatus_status: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DealMemo(TypedDict):
    id: str
    artist_id: str
    advance_cents: int
    base_royalty_rate_bps: int
    recoupment_scope: str
    promo_costs_recoupable: bool
    options_total: int
    option_term_months: int
    option_escalation_bps: int
    term_months: int
    valid_until_date: str
    guardian_name: Optional[str]
    guardian_email: Optional[str]
    round_count: int
    contract_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict):
    id: str
    artist_id: str
    deal_memo_id: str
    advance_cents: int
    base_royalty_rate_bps: int
    recoupment_scope: str
    promo_costs_recoupable: bool
    options_total: int
    options_exercised: int
    option_escalation_bps: int
    option_term_months: int
    term_start_date: str
    current_term_end_date: str
    advance_status: str
    effective_base_rate_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RecoupmentAccount(TypedDict):
    id: str
    contract_id: str
    recording_balance_cents: int
    advance_balance_cents: int
    tour_support_balance_cents: int
    promo_balance_cents: int
    total_unrecouped_cents: int
    total_recouped_cents: int
    writeoff_cents: int
    payout_status: str
    created_at: str
    updated_at: str
    version: int


class RecordingProject(TypedDict):
    id: str
    contract_id: str
    title: str
    project_type: str
    budget_cents: int
    spent_cents: int
    committed_cents: int
    budget_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RecordingMilestone(TypedDict):
    id: str
    project_id: str
    name: str
    sequence: int
    due_date: str
    payment_cents: int
    deliverable_note: Optional[str]
    approved_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Track(TypedDict):
    id: str
    project_id: str
    title: str
    duration_seconds: int
    isrc: str
    contains_sample: bool
    clearance_ref: Optional[str]
    version_of_track_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Release(TypedDict):
    id: str
    contract_id: str
    project_id: str
    title: str
    release_type: str
    release_date: str
    track_ids: List[str]
    went_live_date: Optional[str]
    asset_status: str
    distribution_status: str
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict):
    id: str
    label_id: str
    name: str
    channel_type: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class AssetDelivery(TypedDict):
    id: str
    release_id: str
    distributor_id: str
    attempt_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketingBeat(TypedDict):
    id: str
    release_id: str
    beat_type: str
    channel: str
    start_date: str
    end_date: str
    budget_cents: int
    impressions: Optional[int]
    engagement_score: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PromoCampaign(TypedDict):
    id: str
    release_id: str
    channel: str
    start_date: str
    end_date: str
    spend_cap_cents: int
    spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TourSupport(TypedDict):
    id: str
    contract_id: str
    tour_name: str
    requested_amount_cents: int
    approved_budget_cents: Optional[int]
    advanced_amount_cents: Optional[int]
    approved_expense_total_cents: int
    unspent_returned_cents: Optional[int]
    approved_by_user_id: Optional[str]
    funded_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TourExpense(TypedDict):
    id: str
    tour_support_id: str
    category: str
    amount_cents: int
    expense_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: common_fields false. ONLY id + created_at.
class RevenueReport(TypedDict):
    id: str
    label_id: str
    distributor_id: str
    release_id: str
    period: str
    channel: str
    units: int
    gross_revenue_cents: int
    note: Optional[str]
    created_at: str


class RoyaltyRun(TypedDict):
    id: str
    label_id: str
    period: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    run_id: str
    contract_id: str
    period: str
    gross_revenue_cents: int
    net_revenue_cents: int
    royalty_earned_cents: int
    projected_recoupment_cents: int
    recoupment_applied_cents: int
    reserve_held_cents: int
    adjustment_cents: int
    net_payable_cents: int
    dispute_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
