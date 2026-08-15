"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums (one per entity lifecycle)
# ---------------------------------------------------------------------------

class ProjectStatus(str, Enum):
    SETUP = "SETUP"
    ACTIVE = "ACTIVE"
    WRAPPING = "WRAPPING"
    CLOSED = "CLOSED"
    ARCHIVED = "ARCHIVED"


class SecurityTier(str, Enum):
    STANDARD = "STANDARD"
    ELEVATED = "ELEVATED"
    LOCKDOWN = "LOCKDOWN"


class MediaBatchStatus(str, Enum):
    DECLARED = "DECLARED"
    INGESTING = "INGESTING"
    PROXYING = "PROXYING"
    READY = "READY"
    FAILED = "FAILED"
    PURGED = "PURGED"


class MediaAssetStatus(str, Enum):
    INGESTED = "INGESTED"
    VERIFIED = "VERIFIED"
    CONFORMED = "CONFORMED"
    LOCKED = "LOCKED"
    FAILED = "FAILED"
    PURGED = "PURGED"


class ProxyStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


class WatermarkProfileStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class WatermarkPosition(str, Enum):
    TOP_LEFT = "TOP_LEFT"
    TOP_RIGHT = "TOP_RIGHT"
    BOTTOM_LEFT = "BOTTOM_LEFT"
    BOTTOM_RIGHT = "BOTTOM_RIGHT"
    CENTER = "CENTER"
    DIAGONAL_TILE = "DIAGONAL_TILE"


class DailiesPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    REVOKED = "REVOKED"


class EditBayStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    DECOMMISSIONED = "DECOMMISSIONED"


class BayType(str, Enum):
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"
    COLOR = "COLOR"
    SOUND = "SOUND"
    QC = "QC"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class TurnoverPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    STAGED = "STAGED"
    ISSUED = "ISSUED"
    ACKED = "ACKED"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    VOID = "VOID"


class TurnoverKind(str, Enum):
    CONFORM = "CONFORM"
    COLOR = "COLOR"
    SOUND = "SOUND"


class ChangeListStatus(str, Enum):
    OPEN = "OPEN"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class ChangeOperation(str, Enum):
    ADD = "ADD"
    DELETE = "DELETE"
    TRIM = "TRIM"
    SLIP = "SLIP"


class ReviewRoundStatus(str, Enum):
    OPEN = "OPEN"
    NOTES_CLOSED = "NOTES_CLOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    VOID = "VOID"


class ReviewTargetKind(str, Enum):
    DAILIES = "DAILIES"
    CUT = "CUT"
    VENDOR_RETURN = "VENDOR_RETURN"
    DELIVERABLE = "DELIVERABLE"


class ReviewNoteStatus(str, Enum):
    OPEN = "OPEN"
    ACKED = "ACKED"
    RESOLVED = "RESOLVED"
    VOID = "VOID"


class ReviewSeverity(str, Enum):
    INFO = "INFO"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class DeliverableStatus(str, Enum):
    SPEC_DRAFT = "SPEC_DRAFT"
    RENDERING = "RENDERING"
    RENDERED = "RENDERED"
    QC_QUEUED = "QC_QUEUED"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SpecKind(str, Enum):
    MEZZANINE = "MEZZANINE"
    BROADCAST = "BROADCAST"


class Container(str, Enum):
    MXF_OP1A = "MXF_OP1A"
    MOV_PRORES = "MOV_PRORES"
    IMF = "IMF"


class QCVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ArchiveJobStatus(str, Enum):
    QUEUED = "QUEUED"
    WRITING = "WRITING"
    VERIFYING = "VERIFYING"
    SEALED = "SEALED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class LtoGeneration(str, Enum):
    LTO7 = "LTO7"
    LTO8 = "LTO8"
    LTO9 = "LTO9"


class ArchiveScope(str, Enum):
    SOURCES_ONLY = "SOURCES_ONLY"
    SOURCES_AND_PROXIES = "SOURCES_AND_PROXIES"
    FULL_PROJECT = "FULL_PROJECT"


class VendorStatus(str, Enum):
    ONBOARDED = "ONBOARDED"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class VendorCapability(str, Enum):
    CONFORM = "CONFORM"
    COLOR = "COLOR"
    SOUND = "SOUND"
    QC = "QC"
    ARCHIVE = "ARCHIVE"


class VendorBidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WITHDRAWN = "WITHDRAWN"
    AWARDED = "AWARDED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    POST_SUPERVISOR = "PostSupervisor"
    MEDIA_MANAGER = "MediaManager"
    DAILIES_COORDINATOR = "DailiesCoordinator"
    CONFORM_EDITOR = "ConformEditor"
    REVIEWER_LEAD = "ReviewerLead"
    QC_OPERATOR = "QCOperator"
    FACILITY_ADMIN = "FacilityAdmin"
    VENDOR_REP = "VendorRep"
    ARTIST = "Artist"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Project(TypedDict, total=False):
    id: str
    title: str
    client_code: str
    fps: float
    resolution_width: int
    resolution_height: int
    storage_quota_gb: int
    storage_used_gb: float
    security_tier: str
    status: str
    open_change_list_count: int
    conform_ready: bool
    created_at: str
    updated_at: str
    version: int


class MediaBatch(TypedDict, total=False):
    id: str
    project_id: str
    batch_label: str
    ingest_window_start: str
    ingest_window_end: str
    status: str
    asset_count: int
    failed_asset_count: int
    proxy_progress_pct: int
    created_at: str
    updated_at: str
    version: int


class MediaAsset(TypedDict, total=False):
    id: str
    project_id: str
    batch_id: str
    reel_name: str
    clip_name: str
    source_bytes: int
    proxy_bytes: int
    duration_frames: int
    proxy_status: str
    status: str
    qc_fail_count: int
    retained_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WatermarkProfile(TypedDict, total=False):
    id: str
    project_id: str
    profile_name: str
    opacity_pct: int
    position: str
    includes_recipient_email: bool
    forensic_enabled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class DailiesPackage(TypedDict, total=False):
    id: str
    project_id: str
    batch_id: str
    watermark_profile_id: str
    distribution_list: List[str]
    status: str
    published_at: Optional[str]
    revoked_at: Optional[str]
    recipient_count: int
    created_at: str
    updated_at: str
    version: int


class EditBay(TypedDict, total=False):
    id: str
    project_id: str
    bay_name: str
    bay_type: str
    capacity_hours_per_day: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    project_id: str
    bay_id: str
    artist_email: str
    session_date: str
    start_hour: int
    end_hour: int
    version_tag: str
    status: str
    booked_hours: int
    created_at: str
    updated_at: str
    version: int


class TurnoverPackage(TypedDict, total=False):
    id: str
    project_id: str
    turnover_kind: str
    sequence_label: str
    vendor_id: Optional[str]
    status: str
    issued_at: Optional[str]
    change_list_revision: int
    created_at: str
    updated_at: str
    version: int


class ChangeList(TypedDict, total=False):
    id: str
    project_id: str
    turnover_id: str
    revision: int
    entries: list
    net_frames_delta: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReviewRound(TypedDict, total=False):
    id: str
    project_id: str
    round_label: str
    target_kind: str
    target_ref_id: str
    status: str
    unresolved_critical: bool
    open_note_count: int
    created_at: str
    updated_at: str
    version: int


class ReviewNote(TypedDict, total=False):
    id: str
    project_id: str
    round_id: str
    author_email: str
    severity: str
    body: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Deliverable(TypedDict, total=False):
    id: str
    project_id: str
    spec_kind: str
    sequence_label: str
    container: str
    requires_qc: bool
    status: str
    render_progress_pct: int
    qc_attempt_count: int
    created_at: str
    updated_at: str
    version: int


# QCReport carries ONLY id + created_at — no updated_at, no version
class QCReport(TypedDict, total=False):
    id: str
    project_id: str
    deliverable_id: str
    asset_id: Optional[str]
    attempt_no: int
    verdict: str
    fail_codes: List[str]
    issued_by: str
    created_at: str


class ArchiveJob(TypedDict, total=False):
    id: str
    project_id: str
    lto_generation: str
    target_scope: str
    retention_years: int
    status: str
    sealed_at: Optional[str]
    bytes_written: int
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    vendor_name: str
    capabilities: List[str]
    day_rate_cents: int
    capacity_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VendorBid(TypedDict, total=False):
    id: str
    project_id: str
    turnover_id: str
    vendor_id: str
    bid_amount_cents: int
    eta_days: int
    status: str
    created_at: str
    updated_at: str
    version: int
