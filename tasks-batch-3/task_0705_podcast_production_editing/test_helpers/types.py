"""Domain types: entity TypedDicts, status enums, role enum.

Every entity in this service carries the full common set (id, created_at,
updated_at, version): the PRD states no resource is immutable-after-creation,
so none omits updated_at or version.
"""
from enum import Enum
from typing import TypedDict, Optional


# --- Roles ---
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SHOW_OWNER = "ShowOwner"
    PRODUCER_ENG = "ProducerEng"
    AD_OPS = "AdOps"


# --- Status enums ---
class ShowPosture(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    SUSPENDED = "SUSPENDED"


class ShowFormat(str, Enum):
    INTERVIEW = "INTERVIEW"
    SOLO = "SOLO"
    PANEL = "PANEL"
    NARRATIVE = "NARRATIVE"


class BillingModel(str, Enum):
    PER_EPISODE = "PER_EPISODE"
    RETAINER = "RETAINER"


class ContractTier(str, Enum):
    STANDARD = "STANDARD"
    PRIORITY = "PRIORITY"
    RUSH = "RUSH"


class EngagementType(str, Enum):
    PER_EPISODE = "PER_EPISODE"
    RETAINER = "RETAINER"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class RetainerCycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class EpisodeStatus(str, Enum):
    INTAKE = "INTAKE"
    RECORDING = "RECORDING"
    EDITING = "EDITING"
    REVIEW = "REVIEW"
    MASTERED = "MASTERED"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"
    CANCELLED = "CANCELLED"


class CaptureMode(str, Enum):
    STUDIO = "STUDIO"
    REMOTE = "REMOTE"


class SessionStatus(str, Enum):
    BOOKED = "BOOKED"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliverableKind(str, Enum):
    MASTER_AUDIO = "MASTER_AUDIO"
    SHOW_NOTES = "SHOW_NOTES"
    TRANSCRIPT = "TRANSCRIPT"


class DeliverableStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    DELIVERED = "DELIVERED"


class AssetVersionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InvoiceKind(str, Enum):
    PER_EPISODE = "PER_EPISODE"
    RETAINER_OVERAGE = "RETAINER_OVERAGE"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    DISPUTED = "DISPUTED"
    VOID = "VOID"


class AdCampaignStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class AdPlacement(str, Enum):
    PRE_ROLL = "PRE_ROLL"
    MID_ROLL = "MID_ROLL"
    POST_ROLL = "POST_ROLL"


# --- Entity TypedDicts (all carry id/created_at/updated_at/version) ---
class Show(TypedDict):
    id: str
    title: str
    format: str
    target_loudness_lufs: float
    billing_model: str
    lifetime_billed_cents: int
    production_posture: str
    open_episode_count: int
    created_at: str
    updated_at: str
    version: int


class EngagementContract(TypedDict):
    id: str
    show_id: str
    tier: str
    engagement_type: str
    monthly_included_episodes: int
    loyalty_discount_pct: float
    status: str
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetainerCycle(TypedDict):
    id: str
    contract_id: str
    cycle_start_utc: str
    cycle_end_utc: str
    status: str
    included_consumed: int
    overage_episode_count: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Episode(TypedDict):
    id: str
    show_id: str
    contract_id: str
    title: str
    planned_track_count: int
    raw_track_count: int
    transcript_requested: bool
    recording_ended_at: Optional[str]
    assets_complete_at: Optional[str]
    turnaround_due_utc: Optional[str]
    delivered_late: bool
    status: str
    revision_count: int
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict):
    id: str
    episode_id: str
    engineer_id: str
    capture_mode: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Engineer(TypedDict):
    id: str
    name: str
    remote_buffer_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict):
    id: str
    episode_id: str
    kind: str
    current_version_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AssetVersion(TypedDict):
    id: str
    deliverable_id: str
    supersedes_version_id: Optional[str]
    version_no: int
    integrated_loudness_lufs: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    show_id: str
    episode_id: Optional[str]
    retainer_cycle_id: Optional[str]
    kind: str
    subtotal_cents: int
    discount_cents: int
    late_fee_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdCampaign(TypedDict):
    id: str
    show_id: str
    sponsor_name: str
    platform_fee_pct: float
    show_payout_cents: int
    platform_take_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AdSlot(TypedDict):
    id: str
    campaign_id: str
    episode_id: str
    placement: str
    gross_cents: int
    created_at: str
    updated_at: str
    version: int
