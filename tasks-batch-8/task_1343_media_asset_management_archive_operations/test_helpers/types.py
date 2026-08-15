"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    INGEST_COORDINATOR = "IngestCoordinator"
    METADATA_CATALOGER = "MetadataCataloger"
    METADATA_LIBRARIAN = "MetadataLibrarian"
    ARCHIVIST_LEAD = "ArchivistLead"
    RIGHTS_MANAGER = "RightsManager"
    LEGAL_COUNSEL = "LegalCounsel"
    ACCESS_OFFICER = "AccessOfficer"
    REQUESTER = "Requester"
    FINANCE_OFFICER = "FinanceOfficer"
    LAB_TECHNICIAN = "LabTechnician"


class IngestBatchStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class CatalogStatus(str, Enum):
    METADATA_DRAFT = "METADATA_DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CATALOGED = "CATALOGED"
    ARCHIVED = "ARCHIVED"
    DISPOSAL_SCHEDULED = "DISPOSAL_SCHEDULED"
    DISPOSED = "DISPOSED"


class StorageTier(str, Enum):
    ONLINE = "ONLINE"
    NEARLINE = "NEARLINE"
    DEEP_ARCHIVE = "DEEP_ARCHIVE"


class RightsPosture(str, Enum):
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"
    EXPIRED = "EXPIRED"


class HoldStatus(str, Enum):
    HELD = "HELD"
    CLEAR = "CLEAR"


class MediaType(str, Enum):
    VIDEO = "VIDEO"
    AUDIO = "AUDIO"
    FILM = "FILM"
    PHOTO = "PHOTO"
    DOCUMENT = "DOCUMENT"


class FormatClass(str, Enum):
    BETACAM_SP = "BETACAM_SP"
    UMATIC = "UMATIC"
    VHS = "VHS"
    FILM_16MM = "FILM_16MM"
    AUDIO_REEL = "AUDIO_REEL"
    AUDIO_DAT = "AUDIO_DAT"
    DIGITAL_FILE = "DIGITAL_FILE"
    PRORES_FILE = "PRORES_FILE"


class ContentRating(str, Enum):
    G = "G"
    PG = "PG"
    PG13 = "PG13"
    R = "R"
    NR = "NR"


class RenditionType(str, Enum):
    PROXY_LOWRES = "PROXY_LOWRES"
    PROXY_HIGHRES = "PROXY_HIGHRES"


class ProxyStatus(str, Enum):
    QUEUED = "QUEUED"
    RENDERING = "RENDERING"
    READY = "READY"
    FAILED = "FAILED"


class GrantType(str, Enum):
    BROADCAST = "BROADCAST"
    STREAMING = "STREAMING"
    SYNDICATION = "SYNDICATION"
    ARCHIVAL_ONLY = "ARCHIVAL_ONLY"


class Territory(str, Enum):
    DOMESTIC = "DOMESTIC"
    REGIONAL = "REGIONAL"
    GLOBAL = "GLOBAL"


class RestrictionFlag(str, Enum):
    EDITORIAL_ONLY = "EDITORIAL_ONLY"
    NO_RERUN = "NO_RERUN"
    NEWS_USE_ONLY = "NEWS_USE_ONLY"
    GEO_BLOCKED = "GEO_BLOCKED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class LegalHoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class DisposalOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    BLOCKED = "BLOCKED"


class RetrievalPurpose(str, Enum):
    BROADCAST = "BROADCAST"
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    EXHIBITION = "EXHIBITION"


class DeliveryTier(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITE = "EXPEDITE"


class RetrievalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    RECALLING = "RECALLING"
    STAGED = "STAGED"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class UsageType(str, Enum):
    BROADCAST = "BROADCAST"
    REBROADCAST = "REBROADCAST"
    STREAMING = "STREAMING"
    PROMO = "PROMO"


class UsageEventStatus(str, Enum):
    REPORTED = "REPORTED"
    VERIFIED = "VERIFIED"
    ROYALTY_POSTED = "ROYALTY_POSTED"
    DISPUTED = "DISPUTED"


class StatementStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    POSTED = "POSTED"


class VolumeTier(str, Enum):
    TIER_0 = "TIER_0"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"


class MigrationStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    HOLD_PAUSED = "HOLD_PAUSED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class TicketStatus(str, Enum):
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    DIGITIZING = "DIGITIZING"
    QC_REVIEW = "QC_REVIEW"
    COMPLETED = "COMPLETED"
    QC_FAILED = "QC_FAILED"
    CANCELLED = "CANCELLED"


class OutputFormat(str, Enum):
    PRORES_FILE = "PRORES_FILE"
    H264_FILE = "H264_FILE"


class WorkstationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MAINTENANCE = "MAINTENANCE"


# --- Entity TypedDicts (all fourteen resources carry the full common set:
# id, created_at, updated_at, version — PRD §2.5) ---

class StaffMember(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    department: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class IngestBatch(TypedDict, total=False):
    id: str
    batch_name: str
    source_department: str
    status: str
    asset_count: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    ingest_batch_id: str
    source_asset_id: Optional[str]
    title: str
    description: str
    media_type: str
    format_class: str
    duration_seconds: int
    size_gb: float
    rights_holder: str
    keywords: List[str]
    content_rating: str
    catalog_status: str
    storage_tier: str
    rights_posture: str
    hold_status: str
    metadata_submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProxyRendition(TypedDict, total=False):
    id: str
    asset_id: str
    rendition_type: str
    status: str
    retry_count: int
    proxy_url: Optional[str]
    indexed_at: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RightsGrant(TypedDict, total=False):
    id: str
    asset_id: str
    grant_type: str
    territory: str
    exclusive: bool
    window_start: str
    window_end: str
    restriction_flags: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LegalHold(TypedDict, total=False):
    id: str
    asset_id: str
    matter_reference: str
    reason: str
    placed_by_user_id: str
    status: str
    released_by_user_id: Optional[str]
    released_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetentionPolicy(TypedDict, total=False):
    id: str
    media_type: str
    min_retention_years: int
    requires_legal_review: bool
    created_at: str
    updated_at: str
    version: int


class DisposalOrder(TypedDict, total=False):
    id: str
    asset_id: str
    created_by_user_id: str
    scheduled_execution_date: str
    retention_override: bool
    override_reason: Optional[str]
    pinned_asset_version: int
    status: str
    approved_by_user_id: Optional[str]
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetrievalRequest(TypedDict, total=False):
    id: str
    asset_id: str
    requester_id: str
    purpose: str
    delivery_tier: str
    requested_delivery_by: str
    status: str
    quoted_fee_cents: Optional[int]
    return_count: int
    staged_at: Optional[str]
    delivered_at: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UsageEvent(TypedDict, total=False):
    id: str
    asset_id: str
    reported_by_id: str
    usage_type: str
    market_size: int
    duration_seconds_used: int
    aired_at: str
    status: str
    provisional_accrual_cents: Optional[int]
    final_accrual_cents: Optional[int]
    statement_id: Optional[str]
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict, total=False):
    id: str
    rights_holder: str
    period_start: str
    period_end: str
    status: str
    event_ids: List[str]
    total_verified_seconds: int
    volume_tier: Optional[str]
    provisional_total_cents: Optional[int]
    total_accrual_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MigrationJob(TypedDict, total=False):
    id: str
    asset_id: str
    target_tier: str
    status: str
    retry_count: int
    checksum_sha256: Optional[str]
    failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DigitizationTicket(TypedDict, total=False):
    id: str
    asset_id: str
    workstation_id: Optional[str]
    scheduled_start: str
    scheduled_end: str
    output_format: str
    priority_score: int
    status: str
    rework_count: int
    qc_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Workstation(TypedDict, total=False):
    id: str
    name: str
    supported_formats: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int
