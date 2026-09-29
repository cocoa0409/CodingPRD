"""Domain types for the Curtain Wall Fabrication & Installation API.

Entity TypedDicts, status enums and the participant-role enum, all named exactly
as the PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Participant roles (PRD §2.1) — eight roles, all carrying an opaque identity.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    CW_PROJECT_MANAGER = "CWProjectManager"
    CW_DETAILER = "CWDetailer"
    DELEGATED_ENGINEER = "DelegatedEngineer"
    ARCHITECT_OF_RECORD = "ArchitectOfRecord"
    GLAZING_PROCUREMENT = "GlazingProcurement"
    STRUCTURAL_CONTRACTOR = "StructuralContractor"
    FIELD_SUPERINTENDENT = "FieldSuperintendent"
    QC_INSPECTOR = "QCInspector"


ALL_ROLES: List[str] = [role.value for role in UserRole]


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------
class PackageState(str, Enum):
    DESIGN_ASSIST = "DESIGN_ASSIST"
    SYSTEM_SELECTED = "SYSTEM_SELECTED"
    MOCKUP_QUALIFIED = "MOCKUP_QUALIFIED"
    IN_FABRICATION = "IN_FABRICATION"
    IN_INSTALLATION = "IN_INSTALLATION"
    WEATHER_TIGHT_ACHIEVED = "WEATHER_TIGHT_ACHIEVED"
    CLOSED_OUT = "CLOSED_OUT"


class SystemType(str, Enum):
    UNDECIDED = "UNDECIDED"
    UNITIZED = "UNITIZED"
    STICK_BUILT = "STICK_BUILT"


class EngineeringPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class SubmittalState(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    APPROVED_AS_NOTED = "APPROVED_AS_NOTED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    ESCALATED = "ESCALATED"
    VOIDED = "VOIDED"


class SubmittalType(str, Enum):
    SHOP_DRAWING = "SHOP_DRAWING"
    STRUCTURAL_CALCULATION = "STRUCTURAL_CALCULATION"
    COATING_SPEC = "COATING_SPEC"
    MOCKUP_TEST_PLAN = "MOCKUP_TEST_PLAN"


class ReviewDecision(str, Enum):
    APPROVED = "APPROVED"
    APPROVED_AS_NOTED = "APPROVED_AS_NOTED"
    REVISION_REQUIRED = "REVISION_REQUIRED"


class GlassOrderState(str, Enum):
    ORDERED = "ORDERED"
    IN_PRODUCTION = "IN_PRODUCTION"
    RECEIVED = "RECEIVED"
    CLOSED = "CLOSED"


class RiskVariant(str, Enum):
    NOMINAL = "NOMINAL"
    EXPEDITE_ADJUSTED = "EXPEDITE_ADJUSTED"


class ReleaseState(str, Enum):
    RELEASED = "RELEASED"
    REVOKED = "REVOKED"
    CLOSED = "CLOSED"


class RevokedReason(str, Enum):
    SUBMITTAL_REVISION = "SUBMITTAL_REVISION"
    GLASS_RE_FIRE = "GLASS_RE_FIRE"


class FabricationStatus(str, Enum):
    BATCHED = "BATCHED"
    GLAZED = "GLAZED"
    SHIPPED = "SHIPPED"
    ON_HOLD = "ON_HOLD"


class BreakageDrawStatus(str, Enum):
    DRAWN = "DRAWN"
    CANCELLED = "CANCELLED"


class BreakageReason(str, Enum):
    FIELD_BREAKAGE = "FIELD_BREAKAGE"
    COATING_DEFECT = "COATING_DEFECT"
    HANDLING_DAMAGE = "HANDLING_DAMAGE"
    MOCKUP_CONSUMPTION = "MOCKUP_CONSUMPTION"


class MockupTestState(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class EmbedSurveyState(str, Enum):
    PENDING_SURVEY = "PENDING_SURVEY"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    POURED = "POURED"


class InstallStatus(str, Enum):
    PLANNED = "PLANNED"
    ANCHORS_SET = "ANCHORS_SET"
    PANELS_HUNG = "PANELS_HUNG"


class WeatherStatus(str, Enum):
    NOT_TIGHT = "NOT_TIGHT"
    WEATHER_TIGHT = "WEATHER_TIGHT"
    REMEDIATION = "REMEDIATION"


class ElevationLabel(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class AnchorType(str, Enum):
    SLOTTED = "SLOTTED"
    PINNED = "PINNED"
    FIXED = "FIXED"


class CrewDayStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class RigKind(str, Enum):
    MAST_CLIMBER = "MAST_CLIMBER"
    TOWER_CRANE = "TOWER_CRANE"
    MONORAIL = "MONORAIL"


class RigStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    CANCELLED = "CANCELLED"


class FieldTestKind(str, Enum):
    WATER_AAMA_501_2 = "WATER_AAMA_501_2"
    AIR_INFILTRATION = "AIR_INFILTRATION"
    STRUCTURAL_DEFLECTION = "STRUCTURAL_DEFLECTION"


class FieldTestState(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class OutcomeReason(str, Enum):
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    WATER_PENETRATION = "WATER_PENETRATION"
    AIR_LEAKAGE_EXCEEDED = "AIR_LEAKAGE_EXCEEDED"
    DEFLECTION_EXCEEDED = "DEFLECTION_EXCEEDED"


class DefectOrigin(str, Enum):
    MOCKUP_TEST = "MOCKUP_TEST"
    FIELD_TEST = "FIELD_TEST"
    PUNCH_LIST = "PUNCH_LIST"
    ARCHITECT_REVIEW = "ARCHITECT_REVIEW"


class DefectSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class DefectStatus(str, Enum):
    OPEN = "OPEN"
    REMEDIATION_SUBMITTED = "REMEDIATION_SUBMITTED"
    CLOSED = "CLOSED"
    WAIVED = "WAIVED"


class HoldReason(str, Enum):
    SUBMITTAL_REVISION = "SUBMITTAL_REVISION"
    GLASS_RE_FIRE = "GLASS_RE_FIRE"


# ---------------------------------------------------------------------------
# Entity shapes
#
# Almost every resource carries id + created_at + updated_at + version
# (PRD §2.4). Test laboratories are the single exception: they carry only
# id and created_at, with no updated_at and no version.
# ---------------------------------------------------------------------------
class FacadePackage(TypedDict):
    id: str
    name: str
    floor_count: int
    total_area_sqm: float
    contract_value_cents: int
    unit_rate_cents_per_sqm: int
    base_labor_rate_cents_per_hour: int
    design_temp_delta_c: float
    weather_tightness_deadline_date: str
    system_type: str
    state: str
    engineering_posture: str
    blocking_submittal_count: int
    open_critical_defect_count: int
    planned_shop_hours: float
    planned_field_crew_size: int
    certified_area_sqm: float
    earned_value_certified_cents: int
    retention_held_cents: int
    weather_tight_zone_count: int
    mockup_qualified: bool
    created_at: str
    updated_at: str
    version: int


class ShopDrawingSubmittal(TypedDict):
    id: str
    package_id: str
    submittal_type: str
    title: str
    drawing_set_ref: str
    delegated_design_scope: bool
    state: str
    revision_cycle: int
    open_notes_count: int
    sealed_by_user_id: Optional[str]
    seal_license_no: Optional[str]
    sealed_at: Optional[str]
    reviewed_by_user_id: Optional[str]
    review_decision: Optional[str]
    escalation_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GlassOrder(TypedDict):
    id: str
    package_id: str
    supplier_name: str
    coating_code: str
    quoted_lead_time_days: int
    ordered_lites: int
    expedite_authorized: bool
    state: str
    expedite_tier: int
    coating_revision_count: int
    re_fire_required: bool
    received_lites: int
    risk_score: float
    effective_lead_days: int
    risk_variant: str
    risk_flag: bool
    last_risk_computed_at: Optional[str]
    committable_lites: int
    allocated_lites: int
    breakage_stock_lites: int
    available_stock_lites: int
    drawn_lites: int
    unallocated_lites: int
    created_at: str
    updated_at: str
    version: int


class FabricationRelease(TypedDict):
    id: str
    package_id: str
    submittal_id: str
    glass_order_id: str
    panels_per_zone: int
    lites_per_panel: int
    state: str
    released_at: Optional[str]
    revoked_reason: Optional[str]
    system_type_at_release: str
    lot_count: int
    created_at: str
    updated_at: str
    version: int


class PanelLot(TypedDict):
    id: str
    release_id: str
    glass_order_id: str
    zone_id: str
    lot_code: str
    panel_count: int
    lite_count: int
    fabrication_status: str
    hold_reason: Optional[str]
    status_before_hold: Optional[str]
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BreakageDraw(TypedDict):
    id: str
    glass_order_id: str
    panel_lot_id: str
    quantity_lites: int
    reason: str
    status: str
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


# A laboratory is an immutable accreditation reference: it carries only
# id and created_at. No updated_at, no version.
class TestLab(TypedDict):
    id: str
    name: str
    chamber_capacity: int
    accreditation_ref: str
    created_at: str


class MockupTest(TypedDict):
    id: str
    package_id: str
    test_lab_id: str
    window_start: str
    window_end: str
    chambers_required: int
    retest_of_test_id: Optional[str]
    attempt_no: int
    state: str
    chamber_hours: int
    invoice_subtotal_cents: int
    surcharge_cents: int
    invoice_cents: int
    water_penetration_observed: Optional[bool]
    air_infiltration_cfm: Optional[float]
    structural_deflection_mm: Optional[float]
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnchorEmbedSurvey(TypedDict):
    id: str
    zone_id: str
    embed_layout_ref: str
    planned_anchor_count: int
    tolerance_mm: float
    state: str
    surveyed_anchor_count: Optional[int]
    max_deviation_mm: Optional[float]
    surveyed_by_user_id: Optional[str]
    survey_attempt_count: int
    poured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InstallationZone(TypedDict):
    id: str
    package_id: str
    floor_number: int
    elevation_label: str
    area_sqm: float
    height_m: float
    span_mm: int
    anchor_type: str
    designed_joint_mm: float
    planned_panel_count: int
    budget_crew_hours: float
    install_status: str
    weather_status: str
    thermal_movement_allowance_mm: Optional[float]
    deflection_limit_mm: Optional[float]
    provisional_labor_cost_cents: Optional[int]
    final_labor_cost_cents: Optional[int]
    certified_line_cents: Optional[int]
    weather_tight_at: Optional[str]
    hang_completed_at: Optional[str]
    weather_tight_cycle_count: int
    consumed_crew_hours: float
    remaining_crew_hours: float
    created_at: str
    updated_at: str
    version: int


class CrewDayLog(TypedDict):
    id: str
    zone_id: str
    work_date: str
    crew_size: int
    shift_hours: float
    panels_installed: int
    status: str
    day_index: Optional[int]
    straight_person_hours: float
    overtime_person_hours: float
    day_cost_cents: int
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HoistRig(TypedDict):
    id: str
    package_id: str
    rig_code: str
    rig_kind: str
    capacity_panels_per_shift: int
    changeover_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HoistReservation(TypedDict):
    id: str
    rig_id: str
    zone_id: str
    window_start: str
    window_end: str
    planned_panel_count: int
    blocked_from: str
    blocked_until: str
    status: str
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldTest(TypedDict):
    id: str
    zone_id: str
    test_kind: str
    scheduled_for: str
    attempt_no: int
    state: str
    water_penetration_observed: Optional[bool]
    measured_air_leakage_cfm: Optional[float]
    measured_deflection_mm: Optional[float]
    outcome_reason: Optional[str]
    recorded_by_user_id: Optional[str]
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DefectItem(TypedDict):
    id: str
    package_id: str
    zone_id: Optional[str]
    field_test_id: Optional[str]
    mockup_test_id: Optional[str]
    origin: str
    severity: str
    description: str
    status: str
    raised_by_user_id: str
    reinspect_fail_count: int
    remediation_note: Optional[str]
    reinspected_by_user_id: Optional[str]
    waiver_ref: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EarnedValueRead(TypedDict):
    certified_area_sqm: float
    certified_subtotal_cents: int
    retention_held_cents: int
    earned_value_certified_cents: int
    weather_tight_zone_count: int
    contract_value_cents: int
