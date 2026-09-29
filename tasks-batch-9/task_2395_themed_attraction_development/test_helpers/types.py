"""Domain types for the Themed Attraction Development API.

Status enums, enumerated input vocabularies, role enum and entity TypedDicts,
all named exactly as the PRD names them.
"""
from enum import Enum
from typing import Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    OWNER_REP = "OwnerRep"
    CREATIVE_DIRECTOR = "CreativeDirector"
    RIDE_ENGINEER = "RideEngineer"
    SHOW_PROGRAMMER = "ShowProgrammer"
    THIRD_PARTY_REVIEWER = "ThirdPartyReviewer"
    CONTRACTOR_PM = "ContractorPM"
    PROGRAM_ADMIN = "ProgramAdmin"


ALL_ROLES = [r.value for r in UserRole]


# ─── AttractionProject ────────────────────────────────

class DesignPhase(str, Enum):
    BLUE_SKY = "BLUE_SKY"
    CONCEPT = "CONCEPT"
    SCHEMATIC = "SCHEMATIC"
    DESIGN_DEVELOPMENT = "DESIGN_DEVELOPMENT"
    PRODUCTION = "PRODUCTION"
    INSTALLATION = "INSTALLATION"
    TECHNICAL_REHEARSAL = "TECHNICAL_REHEARSAL"
    SOFT_OPEN = "SOFT_OPEN"
    OPERATIONS_HANDOVER = "OPERATIONS_HANDOVER"


DESIGN_PHASE_LADDER = [p.value for p in DesignPhase]


class ReadinessPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AttractionProject(TypedDict):
    id: str
    project_code: str
    name: str
    design_day_attendance: int
    peak_hour_share: float
    budget_ceiling_cents: int
    virtual_queue_share_pct: float
    required_hourly_capacity_guests: int
    design_phase: str
    readiness_posture: str
    selected_ride_system_id: Optional[str]
    committed_cost_cents: int
    forecast_cost_cents: int
    open_critical_finding_count: int
    open_major_finding_count: int
    queue_capacity_total_guests: int
    show_quality_score: float
    soft_open_validated: bool
    handover_accepted_at: Optional[str]
    ledger_sequence_high_water: int
    created_at: str
    updated_at: str
    version: int


# ─── RideSystem ───────────────────────────────────────

class RideSystemStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    SELECTED = "SELECTED"
    ENGINEERED = "ENGINEERED"
    COMMISSIONED = "COMMISSIONED"


class SystemType(str, Enum):
    DARK_RIDE_TRACKLESS = "DARK_RIDE_TRACKLESS"
    OMNIMOVER = "OMNIMOVER"
    LAUNCH_COASTER = "LAUNCH_COASTER"
    BOAT_FLUME = "BOAT_FLUME"
    MOTION_BASE_THEATER = "MOTION_BASE_THEATER"


class SafetyStandard(str, Enum):
    ASTM_F2291 = "ASTM_F2291"
    EN_13814 = "EN_13814"


class RideSystem(TypedDict):
    id: str
    project_id: str
    vendor_name: str
    system_type: str
    vehicle_count: int
    riders_per_vehicle: int
    block_zone_count: int
    cycle_time_seconds: int
    availability_pct: float
    load_efficiency_pct: float
    show_stops_per_hour: float
    dispatch_interval_seconds: int
    theoretical_hourly_capacity_guests: int
    operational_hourly_capacity_guests: int
    status: str
    safety_standard: Optional[str]
    control_system_spec_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── QueueSegment ─────────────────────────────────────

class QueueSegmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    RETIRED = "RETIRED"


class RoutingType(str, Enum):
    STANDARD = "STANDARD"
    ACCESSIBLE = "ACCESSIBLE"
    VIRTUAL_RETURN = "VIRTUAL_RETURN"


class QueueSegment(TypedDict):
    id: str
    project_id: str
    segment_label: str
    length_meters: float
    width_meters: float
    routing_type: str
    position_index: int
    capacity_guests: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── ShowScene ────────────────────────────────────────

class ShowSceneStatus(str, Enum):
    DRAFT = "DRAFT"
    SEQUENCED = "SEQUENCED"
    PROGRAMMED = "PROGRAMMED"
    VALIDATED = "VALIDATED"
    HELD = "HELD"


class HoldReason(str, Enum):
    SAFETY_FREEZE = "SAFETY_FREEZE"
    BUDGET_FREEZE = "BUDGET_FREEZE"


class ShowScene(TypedDict):
    id: str
    project_id: str
    scene_label: str
    sequence_index: int
    duration_seconds: int
    follows_scene_id: Optional[str]
    status: str
    lighting_score: Optional[float]
    audio_score: Optional[float]
    animation_score: Optional[float]
    effects_score: Optional[float]
    scene_quality_score: Optional[float]
    validating_rehearsal_run_id: Optional[str]
    held_from_status: Optional[str]
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── EffectCue ────────────────────────────────────────

class EffectCueStatus(str, Enum):
    PLANNED = "PLANNED"
    VERIFIED = "VERIFIED"


class DisciplineChannel(str, Enum):
    LIGHTING = "LIGHTING"
    AUDIO = "AUDIO"
    MEDIA = "MEDIA"
    ANIMATION = "ANIMATION"
    SPECIAL_EFFECT = "SPECIAL_EFFECT"


class EffectCue(TypedDict):
    id: str
    scene_id: str
    cue_label: str
    discipline_channel: str
    offset_ms: int
    duration_ms: int
    status: str
    created_at: str
    updated_at: str
    version: int


# ─── DesignPackage ────────────────────────────────────

class DesignPackageStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class DisciplineScope(str, Enum):
    SHOW_SET = "SHOW_SET"
    RIDE_AND_CONTROLS = "RIDE_AND_CONTROLS"
    MEDIA_AND_AV = "MEDIA_AND_AV"
    INTEGRATED = "INTEGRATED"


class DesignPackage(TypedDict):
    id: str
    project_id: str
    ride_system_id: str
    package_label: str
    discipline_scope: str
    base_construction_cost_cents: int
    design_fee_cents: int
    contingency_cents: int
    total_cost_of_work_cents: int
    status: str
    revision_round: int
    pinned_ride_system_version: Optional[int]
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── SafetyReview / SafetyFinding ─────────────────────

class SafetyReviewStatus(str, Enum):
    IN_REVIEW = "IN_REVIEW"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLEARED = "CLEARED"


class SafetyReview(TypedDict):
    id: str
    design_package_id: str
    standard_code: str
    reviewer_user_id: str
    status: str
    open_finding_count: int
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FindingSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class SafetyFindingStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"
    WAIVED = "WAIVED"


class SafetyFinding(TypedDict):
    id: str
    safety_review_id: str
    severity: str
    description: str
    remediation_cost_estimate_cents: int
    status: str
    remediation_note: Optional[str]
    waiver_justification: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── ValueEngineeringItem / VEBallot ──────────────────

class VEItemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"


class BallotDecision(str, Enum):
    APPROVE = "APPROVE"
    ABSTAIN = "ABSTAIN"
    VETO = "VETO"


class ValueEngineeringItem(TypedDict):
    id: str
    project_id: str
    title: str
    gross_saving_cents: int
    rework_loss_pct: float
    implementation_cost_cents: int
    capacity_impact_guests_per_hour: int
    scope_impact_delta_cents: int
    net_saving_cents: Optional[int]
    status: str
    ballot_count: int
    veto_present: bool
    created_at: str
    updated_at: str
    version: int


# An append-only record of an event: it carries only id and created_at.
class VEBallot(TypedDict):
    id: str
    value_engineering_item_id: str
    party_role: str
    decision: str
    comment: Optional[str]
    cast_by_user_id: str
    created_at: str


# ─── RehearsalRun ─────────────────────────────────────

class RehearsalRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"


class RunKind(str, Enum):
    TECHNICAL_REHEARSAL = "TECHNICAL_REHEARSAL"
    CAST_REHEARSAL = "CAST_REHEARSAL"
    SOFT_OPEN = "SOFT_OPEN"


class RehearsalResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class RehearsalRun(TypedDict):
    id: str
    project_id: str
    run_kind: str
    window_start_utc: str
    window_end_utc: str
    status: str
    guests_cycled: Optional[int]
    duration_minutes: Optional[int]
    measured_hourly_throughput_guests: Optional[int]
    pass_threshold_guests: Optional[int]
    result: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── BudgetLedgerEntry ────────────────────────────────

class LedgerEntryKind(str, Enum):
    COMMITMENT = "COMMITMENT"
    CHANGE_ORDER = "CHANGE_ORDER"
    VE_SAVING = "VE_SAVING"
    REVERSAL = "REVERSAL"


# An append-only record of an event: it carries only id and created_at.
class BudgetLedgerEntry(TypedDict):
    id: str
    project_id: str
    entry_kind: str
    amount_cents: int
    memo: str
    sequence_no: int
    reversed: bool
    reversal_of_sequence_no: Optional[int]
    created_at: str


# ─── MaintenanceItem ──────────────────────────────────

class MaintenanceItemStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    HANDED_OVER = "HANDED_OVER"


class Criticality(str, Enum):
    SHOW_CRITICAL = "SHOW_CRITICAL"
    RUN_CRITICAL = "RUN_CRITICAL"
    NON_CRITICAL = "NON_CRITICAL"


class MaintenanceItem(TypedDict):
    id: str
    project_id: str
    part_number: str
    description: str
    criticality: str
    annual_consumption_rate: float
    lead_time_days: int
    recommended_stock_qty: int
    stocked_qty: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
