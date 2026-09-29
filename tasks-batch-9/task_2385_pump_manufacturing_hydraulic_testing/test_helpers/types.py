"""Typed shapes and enum vocabularies for the pump manufacturing API.

The TypedDicts mirror the response payloads described in the PRD entity prose.
Every entity carries `id` and `created_at`; all of them except
MaterialSealConfig and TestPoint also carry `updated_at` and `version`.
"""

from typing import Any, Dict, List, Optional, TypedDict


# ── Role vocabulary (PRD 2.1) ────────────────────────────────────────────────
class Role:
    PLATFORM_ADMIN = "PlatformAdmin"
    APPLICATION_ENGINEER = "ApplicationEngineer"
    HYDRAULIC_APPROVER = "HydraulicApprover"
    FOUNDRY_PARTNER = "FoundryPartner"
    QUALITY_INSPECTOR = "QualityInspector"
    TEST_ENGINEER = "TestEngineer"
    PRODUCTION_PLANNER = "ProductionPlanner"
    WARRANTY_ADJUDICATOR = "WarrantyAdjudicator"


ALL_ROLES = [
    Role.PLATFORM_ADMIN,
    Role.APPLICATION_ENGINEER,
    Role.HYDRAULIC_APPROVER,
    Role.FOUNDRY_PARTNER,
    Role.QUALITY_INSPECTOR,
    Role.TEST_ENGINEER,
    Role.PRODUCTION_PLANNER,
    Role.WARRANTY_ADJUDICATOR,
]


# ── Status vocabularies ──────────────────────────────────────────────────────
class FoundryStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PumpModelStatus:
    ORDERABLE = "ORDERABLE"
    PATTERN_CONSTRAINED = "PATTERN_CONSTRAINED"
    SUPERSEDED = "SUPERSEDED"


class PatternAssetStatus:
    QUALIFIED = "QUALIFIED"
    WORN = "WORN"
    IN_REFURB = "IN_REFURB"
    RETIRED = "RETIRED"


class DutyApplicationStatus:
    OPEN = "OPEN"
    SELECTION_LOCKED = "SELECTION_LOCKED"
    CONTRACTED = "CONTRACTED"
    CLOSED = "CLOSED"


class SelectionStatus:
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUPERSEDED = "SUPERSEDED"


class CastingLotStatus:
    POURED = "POURED"
    INSPECTED = "INSPECTED"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REWORK = "REWORK"
    SCRAPPED = "SCRAPPED"


class CastingDefectStatus:
    REPORTED = "REPORTED"
    DISPOSITIONED_USE_AS_IS = "DISPOSITIONED_USE_AS_IS"
    DISPOSITIONED_REPAIR = "DISPOSITIONED_REPAIR"
    DISPOSITIONED_SCRAP = "DISPOSITIONED_SCRAP"
    REPAIR_VERIFIED = "REPAIR_VERIFIED"


class BuildOrderStatus:
    PLANNED = "PLANNED"
    ASSEMBLED = "ASSEMBLED"
    TESTED = "TESTED"
    REWORK_REQUIRED = "REWORK_REQUIRED"
    CASTING_SHORT = "CASTING_SHORT"
    CLOSED = "CLOSED"


class RunState:
    OPEN = "OPEN"
    POINTS_LOCKED = "POINTS_LOCKED"
    EVALUATED = "EVALUATED"
    CERTIFIED = "CERTIFIED"


class HydraulicStatus:
    NOT_EVALUATED = "NOT_EVALUATED"
    WITHIN_TOLERANCE = "WITHIN_TOLERANCE"
    OUT_OF_TOLERANCE = "OUT_OF_TOLERANCE"


class NpshStatus:
    NOT_VERIFIED = "NOT_VERIFIED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PumpPackageStatus:
    CONFIGURED = "CONFIGURED"
    RELEASED = "RELEASED"
    HELD = "HELD"
    SHIPPED = "SHIPPED"


class RepairKitStatus:
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class KitAllocationStatus:
    RESERVED = "RESERVED"
    ISSUED = "ISSUED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class WarrantyClaimStatus:
    SUBMITTED = "SUBMITTED"
    UNDER_ADJUDICATION = "UNDER_ADJUDICATION"
    INFO_REQUESTED = "INFO_REQUESTED"
    ADJUDICATED_NO_DEFECT = "ADJUDICATED_NO_DEFECT"
    ADJUDICATED_APPLICATION_ERROR = "ADJUDICATED_APPLICATION_ERROR"
    ADJUDICATED_MANUFACTURING = "ADJUDICATED_MANUFACTURING"
    SETTLED = "SETTLED"


# ── Value vocabularies ───────────────────────────────────────────────────────
class Alloy:
    CI_GG25 = "CI_GG25"
    DUCTILE_GGG40 = "DUCTILE_GGG40"
    CD4MCU = "CD4MCU"
    DUPLEX_S31803 = "DUPLEX_S31803"
    CN7M = "CN7M"


class SealType:
    SINGLE_CARTRIDGE = "SINGLE_CARTRIDGE"
    DOUBLE_CARTRIDGE = "DOUBLE_CARTRIDGE"
    DUAL_PRESSURIZED = "DUAL_PRESSURIZED"
    PACKED_GLAND = "PACKED_GLAND"


class FlushPlan:
    API_PLAN_02 = "API_PLAN_02"
    API_PLAN_11 = "API_PLAN_11"
    API_PLAN_23 = "API_PLAN_23"
    API_PLAN_32 = "API_PLAN_32"
    API_PLAN_53B = "API_PLAN_53B"


class ServiceClass:
    CLEAN = "CLEAN"
    CORROSIVE = "CORROSIVE"
    ABRASIVE = "ABRASIVE"
    CORROSIVE_ABRASIVE = "CORROSIVE_ABRASIVE"


class BalanceGrade:
    G1_0 = "G1_0"
    G2_5 = "G2_5"
    G6_3 = "G6_3"


class TestGrade:
    GRADE_1B = "GRADE_1B"
    GRADE_2B = "GRADE_2B"
    GRADE_3B = "GRADE_3B"


class CorrectionBasis:
    AS_TESTED = "AS_TESTED"
    RATED_SPEED_CORRECTED = "RATED_SPEED_CORRECTED"


class ControlType:
    DOL_STARTER = "DOL_STARTER"
    SOFT_STARTER = "SOFT_STARTER"
    VFD = "VFD"
    NONE = "NONE"


class DefectType:
    POROSITY = "POROSITY"
    SHRINKAGE = "SHRINKAGE"
    INCLUSION = "INCLUSION"
    COLD_SHUT = "COLD_SHUT"
    MISRUN = "MISRUN"
    CORE_SHIFT = "CORE_SHIFT"


class Severity:
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class Disposition:
    USE_AS_IS = "USE_AS_IS"
    REPAIR_WELD = "REPAIR_WELD"
    SCRAP = "SCRAP"


class GuaranteeBasis:
    CERTIFIED_CURVE = "CERTIFIED_CURVE"
    SELECTION = "SELECTION"


class Determination:
    NO_DEFECT_FOUND = "NO_DEFECT_FOUND"
    APPLICATION_ERROR = "APPLICATION_ERROR"
    MANUFACTURING_DEFECT = "MANUFACTURING_DEFECT"


class ClaimLineCategory:
    PARTS = "PARTS"
    LABOUR = "LABOUR"
    FREIGHT = "FREIGHT"
    DOWNTIME = "DOWNTIME"


class SelectedBy:
    EXPLICIT = "EXPLICIT"
    SELECTOR = "SELECTOR"


class ApplicationErrorFlag:
    SOLIDS_EXCEEDS_CONFIG = "SOLIDS_EXCEEDS_CONFIG"
    VISCOSITY_EXCEEDS_CONFIG = "VISCOSITY_EXCEEDS_CONFIG"
    NPSHA_BELOW_CERTIFIED = "NPSHA_BELOW_CERTIFIED"
    SPEED_ABOVE_RATED = "SPEED_ABOVE_RATED"


# ── Entity shapes ────────────────────────────────────────────────────────────
class _Versioned(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Foundry(_Versioned):
    foundry_code: str
    name: str
    approved_alloys: List[str]
    concurrent_pour_capacity: int
    status: str
    suspension_reason: Optional[str]


class PumpModel(_Versioned):
    model_code: str
    generation: int
    interchange_group: str
    max_impeller_diameter_mm: float
    min_impeller_diameter_mm: float
    shutoff_head_m: float
    bep_flow_m3h: float
    bep_head_m: float
    bep_efficiency_pct: float
    npshr_at_bep_m: float
    rated_speed_rpm: int
    max_flow_m3h: float
    rotor_mass_kg: float
    balance_grade: str
    superseded_by_model_id: Optional[str]
    status: str
    warranty_defect_count: int
    application_error_count: int
    no_defect_count: int


class PatternAsset(_Versioned):
    pump_model_id: str
    foundry_id: str
    pattern_code: str
    wear_threshold: int
    pours_since_refurb: int
    defect_pours_since_refurb: int
    wear_index: int
    refurb_cycles: int
    status: str


class MaterialSealConfig(TypedDict):
    """No updated_at and no version: this catalogue row is immutable."""

    id: str
    created_at: str
    pump_model_id: str
    config_code: str
    casing_material: str
    impeller_material: str
    seal_type: str
    flush_plan: str
    service_class: str
    max_solids_pct: float
    max_viscosity_cst: float
    max_chloride_ppm: float
    max_temp_c: float
    min_running_clearance_mm: float


class DutyApplication(_Versioned):
    application_code: str
    customer_name: str
    duty_flow_m3h: float
    duty_head_m: float
    npsha_available_m: float
    specific_gravity: float
    viscosity_cst: float
    solids_pct: float
    chloride_ppm: float
    process_temp_c: float
    min_efficiency_pct: float
    test_grade: str
    witness_required: bool
    service_class_required: str
    status: str


class Selection(_Versioned):
    duty_application_id: str
    pump_model_id: str
    material_seal_config_id: str
    trimmed_impeller_diameter_mm: float
    diameter_ratio: float
    predicted_head_m: float
    predicted_efficiency_pct: float
    predicted_shaft_power_kw: float
    npshr_catalog_m: float
    npsh_provisional_margin_m: float
    npsh_safety_factor: float
    npshr_certified_m: float
    npsh_margin_m: float
    min_motor_kw: float
    proposed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    status: str


class CastingLot(_Versioned):
    pattern_asset_id: str
    foundry_id: str
    heat_number: str
    alloy_code: str
    qty_poured: int
    pour_window_start: str
    pour_window_end: str
    qty_scrapped: int
    qty_rework_pending: int
    qty_accepted: int
    committed_build_count: int
    status: str


class CastingDefect(_Versioned):
    casting_lot_id: str
    defect_code: str
    defect_type: str
    severity: str
    affected_qty: int
    reported_by_user_id: str
    dispositioned_by_user_id: Optional[str]
    disposition: Optional[str]
    status: str


class BuildOrder(_Versioned):
    selection_id: str
    casting_lot_id: str
    serial_number: str
    running_clearance_mm: Optional[float]
    residual_unbalance_g_mm: Optional[float]
    seal_flush_plan_installed: Optional[str]
    allowable_unbalance_g_mm: Optional[float]
    rework_cycles: int
    status: str


class TestRun(_Versioned):
    build_order_id: str
    test_speed_rpm: int
    correction_basis: str
    test_grade: str
    witness_required: bool
    speed_ratio: Optional[float]
    head_at_guarantee_m: Optional[float]
    power_at_guarantee_kw: Optional[float]
    efficiency_at_guarantee_pct: Optional[float]
    head_deviation_pct: Optional[float]
    efficiency_deviation_pct: Optional[float]
    npshr_tested_m: Optional[float]
    run_state: str
    hydraulic_status: str
    npsh_status: str


class TestPoint(TypedDict):
    """No updated_at and no version: a measured point is immutable."""

    id: str
    created_at: str
    test_run_id: str
    measured_flow_m3h: float
    measured_head_m: float
    measured_power_kw: float
    measured_npsh3_m: Optional[float]
    is_npsh_point: bool


class PumpPackage(_Versioned):
    build_order_id: str
    test_run_id: str
    baseplate_code: str
    motor_kw: float
    motor_frame: str
    control_type: str
    promised_ship_date: Optional[str]
    actual_ship_date: Optional[str]
    min_motor_kw: float
    guarantee_basis: Optional[str]
    application_error_flagged: bool
    status: str


class RepairKit(_Versioned):
    pump_model_id: str
    kit_code: str
    interchange_group: str
    gen_min: int
    gen_max: int
    preferred_generation: int
    substitution_penalty_pct: float
    unit_price: float
    support_window_start: str
    support_window_end: str
    qty_received_total: int
    qty_on_hand: int
    qty_reserved: int
    qty_issued: int
    qty_consumed_total: int
    status: str


class KitAllocation(_Versioned):
    repair_kit_id: str
    build_order_id: str
    requested_qty: int
    selected_by: str
    substitution_penalty_applied_pct: float
    parts_extended: float
    handling_rate: float
    handling_fee: float
    total_charge: float
    status: str


class WarrantyClaim(_Versioned):
    pump_package_id: str
    as_found_flow_m3h: float
    as_found_head_m: float
    as_found_npsha_m: float
    as_found_solids_pct: float
    as_found_viscosity_cst: float
    as_found_speed_rpm: int
    claim_lines: List[Dict[str, Any]]
    submitted_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    info_request_note: Optional[str]
    liability_basis: Optional[str]
    expected_head_m: Optional[float]
    head_shortfall_pct: Optional[float]
    application_error_flags: List[str]
    determination: Optional[str]
    months_since_ship: Optional[int]
    coverage_factor: Optional[float]
    settlement_subtotal: Optional[float]
    admin_fee: Optional[float]
    settlement_total: Optional[float]
    status: str


# Entities whose rows carry updated_at and version.
VERSIONED_ENTITIES = [
    "Foundry",
    "PumpModel",
    "PatternAsset",
    "DutyApplication",
    "Selection",
    "CastingLot",
    "CastingDefect",
    "BuildOrder",
    "TestRun",
    "PumpPackage",
    "RepairKit",
    "KitAllocation",
    "WarrantyClaim",
]

# Entities whose rows carry only id and created_at.
UNVERSIONED_ENTITIES = ["MaterialSealConfig", "TestPoint"]
