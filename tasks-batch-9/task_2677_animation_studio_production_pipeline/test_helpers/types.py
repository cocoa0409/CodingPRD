"""Typed shapes for the thirteen entity types of the Studio Production Pipeline.

Field names mirror the PRD exactly.  Every entity carries the four common
properties of §2.4 (``id``, ``created_at``, ``updated_at``, ``version``).
"""

from typing import Any, Dict, List, Optional

try:  # pragma: no cover - typing shim for older interpreters
    from typing import Literal, TypedDict
except ImportError:  # pragma: no cover
    from typing_extensions import Literal, TypedDict  # type: ignore

JsonDict = Dict[str, Any]

ProductionPhase = Literal["PRE_PRODUCTION", "PRODUCTION_ACTIVE", "DELIVERY", "WRAPPED"]
ProductionFormat = Literal["FEATURE", "SERIES_EPISODE", "SHORT"]
ColorSpace = Literal["ACEScg", "LogC", "Rec709", "sRGB"]
GateType = Literal["SCRIPT", "STORYBOARD", "ANIMATIC", "DESIGN"]
GateStatus = Literal["DRAFT", "IN_REVIEW", "CHANGES_REQUESTED", "APPROVED", "LOCKED"]
AssetType = Literal["CHARACTER_MODEL", "PROP", "ENVIRONMENT", "RIG", "SURFACING_PACKAGE"]
BuildStatus = Literal["BRIEFED", "MODELING", "RIGGING", "SURFACING", "PUBLISHED", "RETIRED"]
LibraryStatus = Literal["PRIVATE", "LIBRARY_CANDIDATE", "LIBRARY_APPROVED", "LIBRARY_DEPRECATED"]
ShotStatus = Literal["BLOCKED_PREPROD", "READY", "IN_PRODUCTION", "COMPLETE"]
Stage = Literal["LAYOUT", "ANIMATION", "EFFECTS", "LIGHTING", "COMP"]
TaskStatus = Literal[
    "NOT_STARTED", "IN_PROGRESS", "SUBMITTED", "IN_REVIEW", "RETAKE", "APPROVED"
]
CalibrationStatus = Literal["UNCALIBRATED", "CALIBRATED", "EXPIRED"]
SessionType = Literal["DAILIES", "DIRECTOR_REVIEW", "CLIENT_REVIEW"]
SessionStatus = Literal["SCHEDULED", "IN_PROGRESS", "CLOSED", "CANCELLED"]
NoteSeverity = Literal["MINOR", "MAJOR", "BLOCKING"]
NoteStatus = Literal["OPEN", "RETAKE_ISSUED", "RESOLVED", "WAIVED"]
RenderPriority = Literal["LOW", "NORMAL", "HIGH", "CRITICAL"]
RenderJobStatus = Literal["RESERVED", "COMPLETED", "FAILED", "CANCELLED", "PREEMPTED"]
CertificationLevel = Literal["NONE", "TIER1", "TIER2", "TIER3"]
PartnerStatus = Literal["ONBOARDING", "APPROVED", "SUSPENDED"]
SecurityTier = Literal["TIER1", "TIER2", "TIER3"]
PackageStatus = Literal[
    "DRAFT", "ISSUED", "IN_PROGRESS", "DELIVERED", "QC_PASSED", "QC_FAILED", "RECALLED"
]
DeliverableType = Literal["MASTER_EXR", "PROXY_MP4", "AUDIO_STEM", "SHOT_PLATE"]
DeliverableStatus = Literal[
    "DRAFT", "SUBMITTED", "QC_PASSED", "QC_FAILED", "SUPERSEDED", "DELIVERED"
]
EarnedValueVariant = Literal["STAGE_WEIGHT", "HOURS_PROGRESS"]


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Production(CommonFields, total=False):
    title: str
    production_code: str
    format: ProductionFormat
    phase: ProductionPhase
    budget_cents: int
    render_allowance_cents: int
    contingency_pct: float
    master_color_space: ColorSpace
    approved_color_spaces: List[ColorSpace]
    gate_types: List[GateType]
    shot_count: int
    completed_shot_count: int
    at_risk_shot_count: int
    total_retake_count: int
    direct_committed_cents: int
    overhead_fee_cents: int
    total_committed_cents: int
    available_cents: int
    render_committed_cents: int
    render_actual_cents: int
    bcwp_cents: int
    bcws_cents: int
    acwp_cents: int
    cpi: Optional[float]
    spi: Optional[float]


class PreProductionGate(CommonFields, total=False):
    production_id: str
    gate_type: GateType
    sequence_index: int
    status: GateStatus
    revision_count: int
    package_url: Optional[str]
    submitted_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]


class Asset(CommonFields, total=False):
    production_id: str
    asset_code: str
    asset_type: AssetType
    base_complexity_points: float
    build_status: BuildStatus
    library_status: LibraryStatus
    derived_from_asset_id: Optional[str]
    reuse_depth: int
    reuse_discount_pct: float
    effective_complexity_points: float
    reuse_source_stale: bool
    library_submitted_by_user_id: Optional[str]
    library_decided_by_user_id: Optional[str]


class Shot(CommonFields, total=False):
    production_id: str
    shot_code: str
    sequence_code: str
    frame_count: int
    budget_cents: int
    difficulty_factor: float
    planned_start_at: str
    planned_finish_at: str
    status: ShotStatus
    current_stage: Optional[Stage]
    retake_count: int
    escalation_flag: bool
    labor_cost_cents: int
    render_cost_committed_cents: int
    render_cost_actual_cents: int
    bcwp_cents: int
    bcws_cents: int
    acwp_cents: int
    cpi: Optional[float]
    spi: Optional[float]


class ShotStageTask(CommonFields, total=False):
    shot_id: str
    stage: Stage
    stage_order: int
    stage_weight_pct: float
    status: TaskStatus
    budgeted_hours: float
    actual_hours: float
    revision_count: int
    escalated: bool
    outsource_package_id: Optional[str]
    assigned_artist_user_id: Optional[str]
    submitted_by_user_id: Optional[str]
    reviewed_by_user_id: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]


class ScreeningRoom(CommonFields, total=False):
    name: str
    seat_capacity: int
    room_color_space: ColorSpace
    turnover_buffer_minutes: int
    calibration_valid_days: int
    last_calibrated_at: Optional[str]
    calibration_status: CalibrationStatus


class ReviewSession(CommonFields, total=False):
    production_id: str
    screening_room_id: str
    session_type: SessionType
    window_start: str
    window_end: str
    attendee_count: int
    status: SessionStatus
    note_count: int
    retake_issued_count: int
    opened_at: Optional[str]
    closed_at: Optional[str]


class DirectorNote(CommonFields, total=False):
    review_session_id: str
    shot_stage_task_id: str
    severity: NoteSeverity
    note_text: str
    status: NoteStatus
    raised_by_user_id: str
    resolved_by_user_id: Optional[str]


class RenderPool(CommonFields, total=False):
    name: str
    total_cores: int
    cost_per_core_hour_cents: int
    committed_core_hours: float
    reserved_job_count: int


class RenderJob(CommonFields, total=False):
    render_pool_id: str
    shot_stage_task_id: str
    priority: RenderPriority
    requested_cores: int
    window_start: str
    window_end: str
    frame_count: int
    seconds_per_frame: float
    committed_core_hours: float
    cost_per_frame_cents: int
    estimated_cost_cents: int
    status: RenderJobStatus
    actual_seconds_per_frame: Optional[float]
    frames_completed: int
    final_cost_cents: Optional[int]
    preempted_by_render_job_id: Optional[str]


class OutsourcePartner(CommonFields, total=False):
    legal_name: str
    security_certification_level: CertificationLevel
    mfa_enforced: bool
    watermark_required: bool
    status: PartnerStatus
    qc_decided_package_count: int
    quality_score_rolling: float
    quality_score_lifetime: float


class OutsourcePackage(CommonFields, total=False):
    production_id: str
    partner_id: str
    package_code: str
    security_tier: SecurityTier
    fee_cents: int
    fee_committed_cents: int
    quality_min_score: float
    stage_task_ids: List[str]
    status: PackageStatus
    watermark_applied: bool
    delivery_count: int
    qc_score: Optional[int]
    qc_decided_at: Optional[str]


class Deliverable(CommonFields, total=False):
    production_id: str
    shot_id: Optional[str]
    deliverable_type: DeliverableType
    color_space: ColorSpace
    resolution: str
    frame_rate: float
    bit_depth: int
    version_index: int
    version_label: str
    status: DeliverableStatus
    qc_note: Optional[str]
    delivered_at: Optional[str]


class EarnedValueReport(TypedDict, total=False):
    shot_id: str
    variant: EarnedValueVariant
    bcws_cents: int
    bcwp_cents: int
    acwp_cents: int
    cpi: Optional[float]
    spi: Optional[float]
    computed_at: str
