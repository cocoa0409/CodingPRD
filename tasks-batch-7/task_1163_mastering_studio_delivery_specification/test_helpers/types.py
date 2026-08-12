"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    CLIENT = "Client"
    ENGINEER = "Engineer"
    QA_CHECKER = "QAChecker"
    STUDIO_MANAGER = "StudioManager"


class ClientStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EngineerTier(str, Enum):
    JUNIOR = "JUNIOR"
    STAFF = "STAFF"
    SENIOR = "SENIOR"
    MASTER = "MASTER"


class AvailabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ON_LEAVE = "ON_LEAVE"
    INACTIVE = "INACTIVE"


class PlatformCode(str, Enum):
    SPOTIFY = "SPOTIFY"
    APPLE_MUSIC = "APPLE_MUSIC"
    YOUTUBE_MUSIC = "YOUTUBE_MUSIC"
    TIDAL = "TIDAL"
    DEEZER = "DEEZER"
    BANDCAMP = "BANDCAMP"
    VINYL = "VINYL"
    CD = "CD"
    CLUB = "CLUB"


class ContainerFormat(str, Enum):
    WAV = "WAV"
    AIFF = "AIFF"
    FLAC = "FLAC"
    MP3_320 = "MP3_320"
    AAC_256 = "AAC_256"
    DDP = "DDP"
    VINYL_PREMASTER = "VINYL_PREMASTER"


class ProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    BOOKED = "BOOKED"
    INTAKE = "INTAKE"
    QC_PASSED = "QC_PASSED"
    MASTERING = "MASTERING"
    REVISION = "REVISION"
    APPROVED = "APPROVED"
    DELIVERING = "DELIVERING"
    DELIVERED = "DELIVERED"
    ARCHIVED = "ARCHIVED"
    RECALLED = "RECALLED"
    CANCELLED = "CANCELLED"


class SessionSlotStatus(str, Enum):
    HELD = "HELD"
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"


class SourceAssetQCStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class RevisionRoundStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class DeliverableKind(str, Enum):
    DDP = "DDP"
    STEM_PACK = "STEM_PACK"
    INSTRUMENTAL = "INSTRUMENTAL"
    MASTER_WAV = "MASTER_WAV"
    MASTER_FLAC = "MASTER_FLAC"
    MASTER_AAC = "MASTER_AAC"
    VINYL_PREMASTER = "VINYL_PREMASTER"


class DeliverableStatus(str, Enum):
    BUILDING = "BUILDING"
    QC_PENDING = "QC_PENDING"
    QC_FAILED = "QC_FAILED"
    READY = "READY"
    EMBEDDED = "EMBEDDED"
    VERIFIED = "VERIFIED"
    RETIRED = "RETIRED"


class CheckCode(str, Enum):
    LOUDNESS_IN_TOL = "LOUDNESS_IN_TOL"
    TRUE_PEAK_IN_TOL = "TRUE_PEAK_IN_TOL"
    LRA_IN_TOL = "LRA_IN_TOL"
    FORMAT_MATCH = "FORMAT_MATCH"
    ISRC_PRESENT = "ISRC_PRESENT"
    UPC_MATCH = "UPC_MATCH"
    CLIP_FREE = "CLIP_FREE"
    DC_OFFSET_OK = "DC_OFFSET_OK"
    PHASE_COHERENT = "PHASE_COHERENT"


class EmbeddingStatus(str, Enum):
    DRAFT = "DRAFT"
    EMBEDDED = "EMBEDDED"
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    REVOKED = "REVOKED"


class StorageClass(str, Enum):
    HOT = "HOT"
    WARM = "WARM"
    COLD = "COLD"
    GLACIER = "GLACIER"


class RecallStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    RESTORING = "RESTORING"
    RESTORED = "RESTORED"
    FAILED = "FAILED"


class RushTier(str, Enum):
    STANDARD = "STANDARD"
    EXPRESS = "EXPRESS"
    RUSH = "RUSH"
    EMERGENCY = "EMERGENCY"


class Client(TypedDict, total=False):
    id: str
    legal_name: str
    contact_email: str
    status: str
    account_credit_cents: int
    lifetime_revision_count: int
    created_at: str
    updated_at: str
    version: int


class Engineer(TypedDict, total=False):
    id: str
    display_name: str
    tier: str
    hourly_rate_cents: int
    capacity_minutes_per_day: int
    availability_status: str
    active_project_count: int
    created_at: str
    updated_at: str
    version: int


class PlatformProfile(TypedDict, total=False):
    id: str
    platform_code: str
    integrated_lufs: float
    true_peak_dbtp: float
    loudness_range_lu: float
    required_sample_rate_hz: int
    required_bit_depth: int
    container_format: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    client_id: str
    title: str
    upc: Optional[str]
    status: str
    assigned_engineer_id: Optional[str]
    scheduled_start_at: str
    scheduled_duration_minutes: int
    target_platform_profile_id: str
    rush_tier: str
    quoted_price_cents: int
    final_price_cents: int
    current_revision_round_id: Optional[str]
    revision_round_count: int
    archive_bundle_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SessionSlot(TypedDict, total=False):
    id: str
    engineer_id: str
    project_id: Optional[str]
    slot_start_at: str
    slot_end_at: str
    status: str
    held_expires_at: str
    created_at: str
    updated_at: str
    version: int


class SourceAsset(TypedDict, total=False):
    id: str
    project_id: str
    filename: str
    sha256: str
    sample_rate_hz: int
    bit_depth: int
    duration_seconds: float
    channels: int
    qc_status: str
    qc_failure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevisionRound(TypedDict, total=False):
    id: str
    project_id: str
    round_index: int
    status: str
    opened_at: str
    submitted_at: Optional[str]
    resolved_at: Optional[str]
    deadline_at: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict, total=False):
    id: str
    project_id: str
    revision_round_id: str
    deliverable_kind: str
    integrated_lufs: float
    true_peak_dbtp: float
    loudness_range_lu: float
    sample_rate_hz: int
    bit_depth: int
    status: str
    qc_report_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QCReport(TypedDict, total=False):
    id: str
    deliverable_id: str
    project_id: str
    check_code: str
    passed: bool
    measured_value: Optional[float]
    tolerance: Optional[float]
    created_at: str
    updated_at: str
    version: int


class MetadataTag(TypedDict, total=False):
    id: str
    deliverable_id: str
    isrc: str
    upc: Optional[str]
    embedding_status: str
    embedded_at: Optional[str]
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ArchiveBundle(TypedDict, total=False):
    id: str
    project_id: str
    storage_class: str
    archive_size_bytes: int
    recall_status: str
    recalled_at: Optional[str]
    restored_at: Optional[str]
    recall_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class RushTierRule(TypedDict, total=False):
    id: str
    tier: str
    multiplier_bp: int
    sla_hours: int
    surcharge_breach_cents: int
    included_revision_rounds: int
    per_round_cents: int
    created_at: str
    updated_at: str
    version: int
