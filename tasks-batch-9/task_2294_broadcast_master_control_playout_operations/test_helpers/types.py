"""Domain types for the Broadcast Master Control API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    MASTER_CONTROL_OPERATOR = "MasterControlOperator"
    QC_TECHNICIAN = "QCTechnician"
    PROGRAM_DIRECTOR = "ProgramDirector"
    BROADCAST_ENGINEER = "BroadcastEngineer"
    TRAFFIC_COORDINATOR = "TrafficCoordinator"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    STATION_ADMIN = "StationAdmin"


ALL_ROLES = [r.value for r in UserRole]

# The four entity-backed roles and the operator role_class each corresponds to.
ENTITY_BACKED_ROLE_CLASS = {
    "MasterControlOperator": "MASTER_CONTROL",
    "QCTechnician": "QC",
    "ProgramDirector": "PROGRAM_DIRECTOR",
    "BroadcastEngineer": "ENGINEER",
}

OPAQUE_ROLES = ["TrafficCoordinator", "ComplianceOfficer", "StationAdmin"]


# ---------------------------------------------------------------------------
# Controlled vocabularies (PRD §2.9)
# ---------------------------------------------------------------------------

class TransmitterOperationalState(str, Enum):
    FULL_POWER = "FULL_POWER"
    REDUCED_POWER = "REDUCED_POWER"
    OFF_AIR = "OFF_AIR"


class ServiceClass(str, Enum):
    PRIMARY = "PRIMARY"
    SUBCHANNEL = "SUBCHANNEL"


class ResolutionClass(str, Enum):
    HD_1080I = "HD_1080I"
    HD_720P = "HD_720P"
    SD_480I = "SD_480I"


class AllocationState(str, Enum):
    ACTIVE = "ACTIVE"
    STANDBY = "STANDBY"
    STARVED = "STARVED"


class AirStatus(str, Enum):
    DARK = "DARK"
    ON_AIR = "ON_AIR"
    BARS_AND_TONE = "BARS_AND_TONE"
    EAS_OVERRIDE = "EAS_OVERRIDE"


class ChannelPosture(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    DEGRADED_CRITICAL = "DEGRADED_CRITICAL"
    EMERGENCY = "EMERGENCY"
    SUSPENDED = "SUSPENDED"


class OperatorRoleClass(str, Enum):
    MASTER_CONTROL = "MASTER_CONTROL"
    QC = "QC"
    PROGRAM_DIRECTOR = "PROGRAM_DIRECTOR"
    ENGINEER = "ENGINEER"


class OverrideAuthority(str, Enum):
    NONE = "NONE"
    CRAWL_ONLY = "CRAWL_ONLY"
    CRAWL_AND_CUTIN = "CRAWL_AND_CUTIN"
    FULL = "FULL"


class CertificationState(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class OperatorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AssetSource(str, Enum):
    SATELLITE_FEED = "SATELLITE_FEED"
    FILE_DELIVERY = "FILE_DELIVERY"
    LIVE_LINE = "LIVE_LINE"
    LOCAL_ARCHIVE = "LOCAL_ARCHIVE"


class VideoCodec(str, Enum):
    MPEG2 = "MPEG2"
    H264 = "H264"
    H265 = "H265"
    XDCAM = "XDCAM"


class AudioChannelConfig(str, Enum):
    MONO = "MONO"
    STEREO_2_0 = "STEREO_2_0"
    SURROUND_5_1 = "SURROUND_5_1"


FRAME_RATES = [23.976, 29.97, 59.94]


class AssetStatus(str, Enum):
    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    QC_WAIVED = "QC_WAIVED"
    EXPIRED = "EXPIRED"
    RETRACTED = "RETRACTED"


class QCVerdict(str, Enum):
    PASS = "PASS"
    PASS_WITH_EXCEPTION = "PASS_WITH_EXCEPTION"
    FAIL = "FAIL"


class QCBasis(str, Enum):
    INGEST = "INGEST"
    AIR_CHECK = "AIR_CHECK"


class DefectCode(str, Enum):
    LOUDNESS_OUT_OF_SPEC = "LOUDNESS_OUT_OF_SPEC"
    AUDIO_LOSS = "AUDIO_LOSS"
    BLACK_FRAMES = "BLACK_FRAMES"
    CAPTION_MISSING = "CAPTION_MISSING"
    CAPTION_MISTIMED = "CAPTION_MISTIMED"
    FORMAT_MISMATCH = "FORMAT_MISMATCH"
    VIDEO_ARTIFACT = "VIDEO_ARTIFACT"


class PlaylistStatus(str, Enum):
    IMPORTING = "IMPORTING"
    IMPORTED = "IMPORTED"
    VALIDATED = "VALIDATED"
    ARMED = "ARMED"
    ON_AIR = "ON_AIR"
    CLOSED = "CLOSED"
    ABANDONED = "ABANDONED"


class ElementKind(str, Enum):
    PROGRAM = "PROGRAM"
    COMMERCIAL = "COMMERCIAL"
    INTERSTITIAL = "INTERSTITIAL"
    PROMO = "PROMO"
    NETWORK_JOIN = "NETWORK_JOIN"
    LIVE_EVENT = "LIVE_EVENT"
    FILLER = "FILLER"


class PlayoutStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CUED = "CUED"
    PLAYING = "PLAYING"
    PLAYED = "PLAYED"
    TRUNCATED = "TRUNCATED"
    SKIPPED = "SKIPPED"
    PREEMPTED = "PREEMPTED"


class ClearanceStatus(str, Enum):
    UNCLEARED = "UNCLEARED"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class Daypart(str, Enum):
    EARLY_MORNING = "EARLY_MORNING"
    DAYTIME = "DAYTIME"
    EARLY_FRINGE = "EARLY_FRINGE"
    PRIME = "PRIME"
    LATE_NIGHT = "LATE_NIGHT"


class PriorityClass(str, Enum):
    GUARANTEED = "GUARANTEED"
    PREEMPTIBLE = "PREEMPTIBLE"
    REMNANT = "REMNANT"


class SpotOrderStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CREDITED = "PARTIALLY_CREDITED"
    FULLY_AIRED = "FULLY_AIRED"
    CLOSED_WITH_CREDIT = "CLOSED_WITH_CREDIT"


class FeedSource(str, Enum):
    NETWORK_PRIMARY = "NETWORK_PRIMARY"
    NETWORK_ALT = "NETWORK_ALT"
    SYNDICATED_LIVE = "SYNDICATED_LIVE"
    LOCAL_LIVE_EVENT = "LOCAL_LIVE_EVENT"


class BacktimingMode(str, Enum):
    STRICT = "STRICT"
    TOLERANT = "TOLERANT"


class PlanAction(str, Enum):
    PAD_WITH_FILLER = "PAD_WITH_FILLER"
    TRIM_TAIL = "TRIM_TAIL"
    SKIP_ELEMENTS = "SKIP_ELEMENTS"
    HARD_CUT = "HARD_CUT"
    JOIN_IN_PROGRESS = "JOIN_IN_PROGRESS"


class FeedWindowState(str, Enum):
    PLANNED = "PLANNED"
    JOINED = "JOINED"
    BROKEN_AWAY = "BROKEN_AWAY"
    ABANDONED = "ABANDONED"


class AlertClass(str, Enum):
    EAS_MANDATORY = "EAS_MANDATORY"
    SEVERE_WEATHER = "SEVERE_WEATHER"
    BREAKING_NEWS = "BREAKING_NEWS"
    STATION_MESSAGE = "STATION_MESSAGE"


class OverrideMode(str, Enum):
    CRAWL = "CRAWL"
    CUT_IN = "CUT_IN"


class OverrideState(str, Enum):
    PENDING = "PENDING"
    ACTIVE_CRAWL = "ACTIVE_CRAWL"
    ACTIVE_CUTIN = "ACTIVE_CUTIN"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class FaultCode(str, Enum):
    AUDIO_LOSS = "AUDIO_LOSS"
    BLACK_FRAME = "BLACK_FRAME"
    CAPTION_LOSS = "CAPTION_LOSS"
    LOSS_OF_SIGNAL = "LOSS_OF_SIGNAL"
    ENCODER_FAILURE = "ENCODER_FAILURE"
    RF_POWER_FAULT = "RF_POWER_FAULT"
    AUTOMATION_STALL = "AUTOMATION_STALL"


class FaultSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class FaultState(str, Enum):
    DETECTED = "DETECTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ESCALATED = "ESCALATED"
    MITIGATED = "MITIGATED"
    RESOLVED = "RESOLVED"
    AUTO_CLEARED = "AUTO_CLEARED"


class MitigationCode(str, Enum):
    SWITCH_TO_BACKUP = "SWITCH_TO_BACKUP"
    RESTART_ENCODER = "RESTART_ENCODER"
    BARS_AND_TONE = "BARS_AND_TONE"
    MANUAL_BYPASS = "MANUAL_BYPASS"


class AsRunEventKind(str, Enum):
    CUE = "CUE"
    START = "START"
    END = "END"
    TRUNCATION = "TRUNCATION"
    SKIP = "SKIP"
    PREEMPTION = "PREEMPTION"
    OVERRIDE_IN = "OVERRIDE_IN"
    OVERRIDE_OUT = "OVERRIDE_OUT"
    FILLER_INSERT = "FILLER_INSERT"
    JOIN = "JOIN"
    BREAKAWAY = "BREAKAWAY"


class AsRunSource(str, Enum):
    AUTOMATION = "AUTOMATION"
    OPERATOR = "OPERATOR"
    SYSTEM = "SYSTEM"


class NotificationKind(str, Enum):
    POWER_REDUCTION = "POWER_REDUCTION"
    OUTAGE = "OUTAGE"
    RESUMPTION = "RESUMPTION"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    FILED = "FILED"
    LATE_FILED = "LATE_FILED"


# ---------------------------------------------------------------------------
# Entity shapes (PRD §2.5: most resources carry id/created_at/updated_at/version;
# as-run entries and QC reports carry only id and created_at)
# ---------------------------------------------------------------------------

class Transmitter(TypedDict):
    id: str
    facility_id: str
    call_sign: str
    authorized_erp_kw: float
    current_power_pct: float
    operational_state: str
    derate_factor: float
    outage_started_utc: Optional[str]
    last_outage_seconds: Optional[int]
    cumulative_outage_seconds: int
    notification_pending_count: int
    created_at: str
    updated_at: str
    version: int


class Multiplex(TypedDict):
    id: str
    transmitter_id: str
    name: str
    total_capacity_kbps: int
    pilot_reserved_kbps: int
    live_encoder_units_total: int
    effective_capacity_kbps: int
    assigned_kbps: int
    available_kbps: int
    starved_channel_count: int
    live_encoder_units_peak: int
    created_at: str
    updated_at: str
    version: int


class Channel(TypedDict):
    id: str
    multiplex_id: str
    parent_channel_id: Optional[str]
    call_sign: str
    channel_number: str
    service_class: str
    resolution_class: str
    requested_bitrate_kbps: int
    floor_bitrate_kbps: int
    priority_rank: int
    allocated_bitrate_kbps: int
    allocation_state: str
    air_status: str
    posture: str
    open_fault_count: int
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict):
    id: str
    full_name: str
    role_class: str
    override_authority: str
    certification_expires_utc: str
    certification_state: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict):
    id: str
    house_number: str
    title: str
    source: str
    expected_duration_seconds: int
    delivery_deadline_utc: str
    required_resolution_class: str
    captions_required: bool
    received_utc: Optional[str]
    measured_duration_seconds: Optional[int]
    video_codec: Optional[str]
    delivered_resolution_class: Optional[str]
    frame_rate: Optional[float]
    audio_loudness_lkfs: Optional[float]
    audio_channel_config: Optional[str]
    caption_present: Optional[bool]
    caption_language: Optional[str]
    late_delivery: Optional[bool]
    technical_score_ingest: Optional[int]
    technical_score_aircheck: Optional[int]
    qc_verdict: Optional[str]
    status: str
    waived_by_operator_id: Optional[str]
    waiver_justification: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QCReport(TypedDict):
    """Append-only record of fact: id and created_at only (PRD §2.5)."""
    id: str
    asset_id: str
    inspected_by_operator_id: str
    basis: str
    defect_codes: List[str]
    measured_duration_seconds: int
    defect_penalty_points: int
    duration_penalty_points: int
    loudness_penalty_points: int
    fault_penalty_points: int
    technical_score: int
    verdict: str
    superseded: bool
    notes: Optional[str]
    created_at: str


class Playlist(TypedDict):
    id: str
    channel_id: str
    broadcast_day: str
    schedule_start_utc: str
    window_duration_seconds: int
    traffic_revision: int
    status: str
    item_count: int
    blocked_item_count: int
    scheduled_total_seconds: int
    projected_end_variance_seconds: int
    asrun_end_variance_seconds: int
    commercial_seconds_by_hour: Dict[str, int]
    reconciliation_credit_cents: int
    armed_at_utc: Optional[str]
    closed_at_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlaylistItem(TypedDict):
    id: str
    playlist_id: str
    asset_id: Optional[str]
    spot_order_id: Optional[str]
    feed_window_id: Optional[str]
    replaces_item_id: Optional[str]
    sequence_number: int
    element_kind: str
    house_number: Optional[str]
    scheduled_start_utc: str
    scheduled_duration_seconds: int
    max_trim_seconds: int
    playout_status: str
    clearance_status: str
    actual_start_utc: Optional[str]
    measured_duration_seconds: Optional[int]
    is_makegood: bool
    trim_applied_seconds: int
    created_at: str
    updated_at: str
    version: int


class SpotOrder(TypedDict):
    id: str
    channel_id: str
    advertiser_name: str
    order_reference: str
    ordered_spots: int
    unit_duration_seconds: int
    rate_cents_total: int
    daypart: str
    priority_class: str
    makegood_deadline_utc: str
    scheduled_spots: int
    aired_spots: int
    short_aired_spots: int
    credited_spots: int
    unplaced_spots: int
    credit_accrued_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NetworkFeedWindow(TypedDict):
    id: str
    channel_id: str
    feed_source: str
    anchor_sequence_number: int
    join_utc: str
    breakaway_utc: str
    guard_seconds: int
    live_encoder_units: int
    backtiming_mode: str
    plan_action: str
    backtime_pad_seconds: int
    backtime_trim_seconds: int
    residual_dead_air_seconds: int
    late_join_seconds: int
    skipped_item_sequences: List[int]
    plan_computed_utc: str
    state: str
    created_at: str
    updated_at: str
    version: int


class EmergencyOverride(TypedDict):
    id: str
    channel_id: str
    requested_by_operator_id: str
    authorized_by_operator_id: Optional[str]
    alert_class: str
    override_mode: str
    active_mode: Optional[str]
    crawl_text: Optional[str]
    requested_start_utc: str
    expected_duration_seconds: int
    activated_utc: Optional[str]
    released_utc: Optional[str]
    truncated_item_count: int
    preempted_item_count: int
    state: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TechnicalFault(TypedDict):
    id: str
    channel_id: Optional[str]
    transmitter_id: Optional[str]
    playlist_item_id: Optional[str]
    fault_code: str
    severity: str
    detected_utc: str
    cleared_utc: Optional[str]
    duration_seconds: int
    state: str
    mitigation_code: Optional[str]
    acknowledged_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AsRunEntry(TypedDict):
    """Append-only record of fact: id and created_at only (PRD §2.5)."""
    id: str
    playlist_id: str
    playlist_item_id: str
    sequence_number: int
    house_number: Optional[str]
    element_kind: str
    event_kind: str
    event_utc: str
    measured_duration_seconds: int
    source: str
    recorded_by_user_id: Optional[str]
    created_at: str


class RegulatoryNotification(TypedDict):
    id: str
    transmitter_id: str
    kind: str
    triggering_utc: str
    due_utc: str
    filed_utc: Optional[str]
    filed_reference: Optional[str]
    narrative: Optional[str]
    observed_power_pct: Optional[float]
    outage_seconds: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


COMMON_FIELDS_FULL = ["id", "created_at", "updated_at", "version"]
COMMON_FIELDS_APPEND_ONLY = ["id", "created_at"]
