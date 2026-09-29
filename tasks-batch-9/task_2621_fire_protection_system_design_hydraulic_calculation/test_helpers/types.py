"""Domain types: status enums, role enum and entity TypedDicts."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    FIRM_ADMIN = "FirmAdmin"
    DESIGN_ENGINEER = "DesignEngineer"
    QC_REVIEWER = "QcReviewer"
    CONTRACTOR = "Contractor"
    AHJ_REVIEWER = "AhjReviewer"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"


class EngineerDiscipline(str, Enum):
    FIRE_PROTECTION = "FIRE_PROTECTION"
    MECHANICAL = "MECHANICAL"
    ELECTRICAL = "ELECTRICAL"


class ReviewerDiscipline(str, Enum):
    FIRE = "FIRE"
    BUILDING = "BUILDING"
    ELECTRICAL = "ELECTRICAL"


class ProjectStatus(str, Enum):
    DESIGN = "DESIGN"
    PERMIT_REVIEW = "PERMIT_REVIEW"
    PERMITTED = "PERMITTED"
    ACCEPTANCE = "ACCEPTANCE"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    CLOSED_OUT = "CLOSED_OUT"


class DesignPosture(str, Enum):
    OPEN = "OPEN"
    GATED = "GATED"
    FROZEN = "FROZEN"


class OccupancyType(str, Enum):
    STORAGE = "STORAGE"
    MERCANTILE = "MERCANTILE"
    INDUSTRIAL = "INDUSTRIAL"
    ASSEMBLY = "ASSEMBLY"
    HEALTHCARE = "HEALTHCARE"


class HazardClass(str, Enum):
    LIGHT = "LIGHT"
    ORDINARY_1 = "ORDINARY_1"
    ORDINARY_2 = "ORDINARY_2"
    EXTRA_1 = "EXTRA_1"
    EXTRA_2 = "EXTRA_2"


class CommodityClass(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"
    CLASS_IV = "CLASS_IV"
    GROUP_A_PLASTIC = "GROUP_A_PLASTIC"


class SprinklerSystemType(str, Enum):
    WET = "WET"
    DRY = "DRY"
    PREACTION = "PREACTION"


class CalculationMethod(str, Enum):
    AREA_DENSITY = "AREA_DENSITY"
    ROOM_DESIGN = "ROOM_DESIGN"


class CalculationState(str, Enum):
    DRAFT = "DRAFT"
    ITERATING = "ITERATING"
    CONVERGED = "CONVERGED"
    PRESSURE_DEFICIENT = "PRESSURE_DEFICIENT"
    QC_PASSED = "QC_PASSED"
    SEALED = "SEALED"
    REOPENED = "REOPENED"
    ARCHIVED = "ARCHIVED"


class StaleReason(str, Enum):
    QC_REJECTED = "QC_REJECTED"
    MAJOR_COMMENT = "MAJOR_COMMENT"
    HAZARD_RECLASSIFIED = "HAZARD_RECLASSIFIED"


class EvaluationBasis(str, Enum):
    RAW_TEST = "RAW_TEST"
    SEASONAL_ADJUSTED = "SEASONAL_ADJUSTED"


class MarginVerdict(str, Enum):
    ADEQUATE = "ADEQUATE"
    MARGINAL = "MARGINAL"
    INADEQUATE_PUMP_REQUIRED = "INADEQUATE_PUMP_REQUIRED"


class EvaluationState(str, Enum):
    EVALUATED = "EVALUATED"
    SUPERSEDED = "SUPERSEDED"


class FirePumpState(str, Enum):
    SIZED = "SIZED"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"


class SizingVerdict(str, Enum):
    ACCEPTABLE = "ACCEPTABLE"
    REQUIRES_PRESSURE_RELIEF_VALVE = "REQUIRES_PRESSURE_RELIEF_VALVE"
    INSUFFICIENT_SUCTION_AT_150_PCT = "INSUFFICIENT_SUCTION_AT_150_PCT"
    INSUFFICIENT_AT_150_PCT = "INSUFFICIENT_AT_150_PCT"


class AuxiliarySystemType(str, Enum):
    STANDPIPE_CLASS_I = "STANDPIPE_CLASS_I"
    STANDPIPE_CLASS_II = "STANDPIPE_CLASS_II"
    COOKING = "COOKING"
    IN_RACK = "IN_RACK"
    FOAM_DELUGE = "FOAM_DELUGE"
    HAZMAT_DELUGE = "HAZMAT_DELUGE"


class AgentType(str, Enum):
    WET_CHEMICAL = "WET_CHEMICAL"
    AFFF = "AFFF"
    HIGH_EXPANSION_FOAM = "HIGH_EXPANSION_FOAM"
    NONE = "NONE"


class AuxiliarySystemStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COMMISSIONED = "COMMISSIONED"
    DECOMMISSIONED_PENDING_RETEST = "DECOMMISSIONED_PENDING_RETEST"
    WITHDRAWN = "WITHDRAWN"


class ShopDrawingState(str, Enum):
    DRAFT = "DRAFT"
    IN_COORDINATION = "IN_COORDINATION"
    CONFLICTED = "CONFLICTED"
    COORDINATED = "COORDINATED"
    STALE = "STALE"
    ISSUED = "ISSUED"


class Trade(str, Enum):
    STRUCTURAL = "STRUCTURAL"
    MECHANICAL = "MECHANICAL"
    LIGHTING = "LIGHTING"


class TradeClearanceState(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CONFLICT_OPEN = "CONFLICT_OPEN"
    STALE = "STALE"
    LOCKED = "LOCKED"


class ConflictSeverity(str, Enum):
    BLOCKING = "BLOCKING"
    ADVISORY = "ADVISORY"


class TradeClearanceOutcome(str, Enum):
    CLEARED = "CLEARED"
    CONFLICT_OPEN = "CONFLICT_OPEN"


class SubmittalState(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    COMMENTS_ISSUED = "COMMENTS_ISSUED"
    RESPONSE_COMPLETE = "RESPONSE_COMPLETE"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class CommentSeverity(str, Enum):
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFORMATIONAL = "INFORMATIONAL"


class ReviewCommentState(str, Enum):
    OPEN = "OPEN"
    RESPONDED = "RESPONDED"
    RESOLVED = "RESOLVED"
    WITHDRAWN = "WITHDRAWN"


class CommentDisposition(str, Enum):
    RESOLVED = "RESOLVED"
    REJECT_RESPONSE = "REJECT_RESPONSE"
    WITHDRAWN = "WITHDRAWN"


class AcceptanceTestType(str, Enum):
    SYSTEM_FLOW_TEST = "SYSTEM_FLOW_TEST"
    PUMP_FLOW_TEST = "PUMP_FLOW_TEST"
    HYDROSTATIC_TEST = "HYDROSTATIC_TEST"
    STANDPIPE_FLOW_TEST = "STANDPIPE_FLOW_TEST"


class WitnessStatus(str, Enum):
    NOT_SCHEDULED = "NOT_SCHEDULED"
    SCHEDULED = "SCHEDULED"
    WITNESSED_PASS = "WITNESSED_PASS"
    WITNESSED_FAIL = "WITNESSED_FAIL"


class DocumentationStatus(str, Enum):
    PENDING = "PENDING"
    AS_BUILT_SUBMITTED = "AS_BUILT_SUBMITTED"
    AS_BUILT_REJECTED = "AS_BUILT_REJECTED"
    AS_BUILT_ACCEPTED = "AS_BUILT_ACCEPTED"


class AsBuiltDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity shapes. Engineer, AhjReviewer, FlowTest and PipeSizingIteration are
# append-only or reference-only records and carry only id and created_at.
# ---------------------------------------------------------------------------

class Engineer(TypedDict):
    id: str
    full_name: str
    license_state: str
    license_number: str
    license_status: str
    discipline: str
    created_at: str


class AhjReviewer(TypedDict):
    id: str
    full_name: str
    jurisdiction_code: str
    discipline: str
    created_at: str


class FlowTest(TypedDict):
    id: str
    project_id: str
    hydrant_tag: str
    static_psi: float
    residual_psi: float
    flow_gpm: float
    tested_at: str
    created_at: str


class PipeSizingIteration(TypedDict):
    id: str
    hydraulic_calculation_id: str
    iteration_index: int
    pipe_size_in: str
    length_ft: float
    fitting_equivalent_ft: float
    flow_gpm: float
    elevation_change_ft: float
    is_supply_connection: bool
    restart_chain: bool
    friction_loss_psi: float
    elevation_loss_psi: float
    velocity_fps: float
    cumulative_psi_after: float
    in_active_chain: bool
    created_at: str


class Project(TypedDict):
    id: str
    project_number: str
    building_name: str
    jurisdiction_code: str
    jurisdiction_state: str
    occupancy_type: str
    building_height_ft: float
    underground_lead_in_loss_psi: float
    lead_engineer_id: str
    ahj_reviewer_id: str
    status: str
    design_posture: str
    governing_hydraulic_calculation_id: Optional[str]
    governing_demand_gpm: float
    auxiliary_demand_gpm: float
    total_system_demand_gpm: float
    sealed_calculation_count: int
    open_major_comment_count: int
    submittal_cycle_count: int
    review_fee_balance_usd: float
    pump_required_flag: bool
    created_at: str
    updated_at: str
    version: int


class HazardArea(TypedDict):
    id: str
    project_id: str
    label: str
    hazard_class: str
    commodity_class: str
    storage_height_ft: float
    ceiling_height_ft: float
    area_sqft: float
    sprinkler_system_type: str
    ceiling_slope_pct: float
    room_area_sqft: Optional[float]
    enclosure_rating_hours: Optional[float]
    room_has_unprotected_opening: bool
    effective_hazard_class: str
    design_density: float
    design_area_sqft: int
    hose_allowance_gpm: float
    reclassification_count: int
    created_at: str
    updated_at: str
    version: int


class HydraulicCalculation(TypedDict):
    id: str
    project_id: str
    hazard_area_id: str
    method: str
    k_factor: float
    authored_by_engineer_id: str
    state: str
    design_flow_gpm: float
    hose_allowance_gpm: float
    room_design_penalty_gpm: float
    hazard_total_demand_gpm: float
    chain_start_index: int
    iteration_count: int
    end_head_psi: float
    required_psi_at_base_of_riser: float
    deficiency_psi: Optional[float]
    stale_reason: Optional[str]
    qc_reviewed_by_engineer_id: Optional[str]
    sealed_by_engineer_id: Optional[str]
    sealed_at: Optional[str]
    reopened_by_submittal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WaterSupplyEvaluation(TypedDict):
    id: str
    project_id: str
    flow_test_id: str
    governing_hydraulic_calculation_id: str
    evaluation_basis: str
    basis_static_psi: float
    basis_residual_psi: float
    basis_test_flow_gpm: float
    design_demand_gpm: float
    required_psi_at_demand: float
    available_psi_at_demand: float
    safety_margin_psi: float
    safety_margin_pct: float
    margin_verdict: str
    pinned_calculation_iteration_count: int
    pump_sized: bool
    state: str
    created_at: str
    updated_at: str
    version: int


class FirePump(TypedDict):
    id: str
    project_id: str
    water_supply_evaluation_id: str
    model_tag: str
    rated_flow_gpm: float
    suction_psi_at_rated: float
    required_discharge_psi: float
    rated_pressure_psi: int
    churn_discharge_psi: float
    flow_150_pct_gpm: float
    suction_psi_at_150_pct: float
    available_psi_at_150_pct: float
    sizing_verdict: str
    state: str
    created_at: str
    updated_at: str
    version: int


class AuxiliarySystem(TypedDict):
    id: str
    project_id: str
    label: str
    system_type: str
    agent_type: str
    hazard_area_id: Optional[str]
    riser_count: Optional[int]
    appliance_count: Optional[int]
    water_wash_enabled: bool
    in_rack_head_count: Optional[int]
    protected_area_sqft: Optional[float]
    demand_gpm: float
    interlock_required: bool
    interlock_verified: bool
    status: str
    outage_start_at: Optional[str]
    outage_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShopDrawing(TypedDict):
    id: str
    project_id: str
    hydraulic_calculation_id: str
    sheet_number: str
    state: str
    required_trade_count: int
    cleared_trade_count: int
    created_at: str
    updated_at: str
    version: int


class TradeClearance(TypedDict):
    id: str
    shop_drawing_id: str
    trade: str
    elevation_low_in: float
    elevation_high_in: float
    state: str
    conflict_severity: Optional[str]
    note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Submittal(TypedDict):
    id: str
    project_id: str
    included_calculation_ids: List[str]
    cycle_number: int
    review_fee_usd: float
    submitted_at: str
    state: str
    open_comment_count: int
    major_comment_count: int
    reviewed_by_ahj_reviewer_id: Optional[str]
    supersedes_submittal_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewComment(TypedDict):
    id: str
    submittal_id: str
    code_section: str
    severity: str
    description: str
    assigned_engineer_id: Optional[str]
    raised_by_ahj_reviewer_id: str
    state: str
    response_note: Optional[str]
    close_note: Optional[str]
    disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AcceptanceTest(TypedDict):
    id: str
    project_id: str
    test_type: str
    required_flow_gpm: float
    required_residual_psi: float
    witness_status: str
    documentation_status: str
    retest_count: int
    witness_reviewer_id: Optional[str]
    measured_flow_gpm: Optional[float]
    measured_residual_psi: Optional[float]
    witness_window_start: Optional[str]
    witness_window_end: Optional[str]
    as_built_document_ref: Optional[str]
    created_at: str
    updated_at: str
    version: int
