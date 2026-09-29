"""Domain types for the Fastener Cold Heading & Thread Rolling API.

Entity TypedDicts, status enums and the operator role enum, all named exactly as
PRD §2.5 / §3 name them. Every one of the twelve resource types carries the full
system-managed set (``id``, ``created_at``, ``updated_at``, ``version``) because
PRD §2.5 states "No entity in this system omits ``updated_at`` or ``version``;
all twelve resource types carry the full set."
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PROCESS_ENGINEER = "ProcessEngineer"
    HEAT_TREAT_OPERATOR = "HeatTreatOperator"
    QUALITY_INSPECTOR = "QualityInspector"
    QUALITY_MANAGER = "QualityManager"
    SHIPPING_CLERK = "ShippingClerk"
    PLANT_ADMIN = "PlantAdmin"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Enumerations carried on the part specification (PRD §3.1)
# ---------------------------------------------------------------------------
class StrengthClass(str, Enum):
    CLASS_8_8 = "CLASS_8_8"
    CLASS_10_9 = "CLASS_10_9"
    CLASS_12_9 = "CLASS_12_9"
    GRADE_5 = "GRADE_5"
    GRADE_8 = "GRADE_8"
    NONE = "NONE"


class QualificationProgram(str, Enum):
    NONE = "NONE"
    AUTOMOTIVE_PPAP = "AUTOMOTIVE_PPAP"
    AEROSPACE_NADCAP = "AEROSPACE_NADCAP"


class ThreadTiming(str, Enum):
    BEFORE_HEAT_TREAT = "BEFORE_HEAT_TREAT"
    AFTER_HEAT_TREAT = "AFTER_HEAT_TREAT"


class SecondaryOpType(str, Enum):
    THREAD_ROLL = "THREAD_ROLL"
    DRILL = "DRILL"
    SLOT = "SLOT"
    POINT = "POINT"


class PlatingSpec(str, Enum):
    NONE = "NONE"
    ZINC_CLEAR = "ZINC_CLEAR"
    ZINC_NICKEL = "ZINC_NICKEL"
    CADMIUM = "CADMIUM"


class PackagingMode(str, Enum):
    BY_COUNT = "BY_COUNT"
    BY_WEIGHT = "BY_WEIGHT"


# ---------------------------------------------------------------------------
# Steel heat / wire lot (PRD §3.2)
# ---------------------------------------------------------------------------
class SteelGrade(str, Enum):
    SAE_1018 = "SAE_1018"
    SAE_1038 = "SAE_1038"
    SAE_10B21 = "SAE_10B21"
    SAE_4037 = "SAE_4037"


class HeatCertStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    SUSPECTED_COUNTERFEIT = "SUSPECTED_COUNTERFEIT"
    REJECTED = "REJECTED"


class VerifyOutcome(str, Enum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class WireLotStatus(str, Enum):
    DRAWN = "DRAWN"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"


class QuarantineSource(str, Enum):
    NONE = "NONE"
    HEAT_COUNTERFEIT = "HEAT_COUNTERFEIT"
    HEAT_REJECTED = "HEAT_REJECTED"


class LubricantCoating(str, Enum):
    PHOSPHATE = "PHOSPHATE"
    POLYMER = "POLYMER"
    LIME = "LIME"
    NONE = "NONE"


# ---------------------------------------------------------------------------
# Heading tool / furnace (PRD §3.3, §3.5)
# ---------------------------------------------------------------------------
class HeadingToolStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MOUNTED = "MOUNTED"
    WORN = "WORN"
    SCRAPPED = "SCRAPPED"


class FurnaceStatus(str, Enum):
    IDLE = "IDLE"
    OCCUPIED = "OCCUPIED"


# ---------------------------------------------------------------------------
# Production lot (PRD §3.4)
# ---------------------------------------------------------------------------
class LotProcessState(str, Enum):
    SETUP = "SETUP"
    HEADED = "HEADED"
    SECONDARY_IN_PROGRESS = "SECONDARY_IN_PROGRESS"
    SECONDARY_DONE = "SECONDARY_DONE"
    HEAT_TREATED = "HEAT_TREATED"
    PLATED = "PLATED"
    BAKED = "BAKED"
    TESTING = "TESTING"
    TESTED = "TESTED"
    CERTIFIED = "CERTIFIED"
    PACKED = "PACKED"
    SHIPPED = "SHIPPED"
    ABORTED = "ABORTED"


class LotDisposition(str, Enum):
    IN_PROCESS = "IN_PROCESS"
    HOLD = "HOLD"
    QUARANTINED = "QUARANTINED"
    SCRAPPED = "SCRAPPED"


class HoldSource(str, Enum):
    NONE = "NONE"
    TOOL_WEAR = "TOOL_WEAR"
    HT_FAILURE = "HT_FAILURE"
    TEST_REJECT = "TEST_REJECT"
    QUALITY = "QUALITY"
    HEAT_COUNTERFEIT = "HEAT_COUNTERFEIT"


class InspectionSeverity(str, Enum):
    NORMAL = "NORMAL"
    TIGHTENED = "TIGHTENED"


# ---------------------------------------------------------------------------
# Process runs / tests / certificates / packs
# ---------------------------------------------------------------------------
class SecondaryOperationStatus(str, Enum):
    PENDING = "PENDING"
    DONE = "DONE"


class HeatTreatRunStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class HeatTreatResult(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL_HARDNESS = "FAIL_HARDNESS"
    FAIL_DECARB = "FAIL_DECARB"


class QuenchMedium(str, Enum):
    OIL = "OIL"
    WATER = "WATER"
    POLYMER = "POLYMER"


class PlatingRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PLATED = "PLATED"
    BAKING = "BAKING"
    BAKE_COMPLETE = "BAKE_COMPLETE"
    SUPERSEDED = "SUPERSEDED"


class LotTestResult(str, Enum):
    PENDING = "PENDING"
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class CertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"
    REISSUE_PENDING = "REISSUE_PENDING"


class PackUnitStatus(str, Enum):
    OPEN = "OPEN"
    SEALED = "SEALED"
    SHIPPED = "SHIPPED"
    RECALLED = "RECALLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id/created_at/updated_at/version
# ---------------------------------------------------------------------------
class PartSpec(TypedDict):
    id: str
    part_number: str
    thread_designation: str
    strength_class: str
    qualification_program: str
    allowed_steel_grades: List[str]
    blank_mass_g: float
    scrap_allowance_pct: float
    station_count_required: int
    thread_timing: str
    required_secondary_ops: List[str]
    min_core_hardness_hv: float
    max_core_hardness_hv: float
    max_decarb_depth_mm: float
    plating_spec: str
    packaging_mode: str
    nominal_pack_count: int
    pieces_per_kg: float
    count_tolerance_pct: float
    proof_load_kn: float
    he_bake_required: bool
    he_bake_min_minutes: int
    created_at: str
    updated_at: str
    version: int


class SteelHeat(TypedDict):
    id: str
    heat_number: str
    mill_code: str
    grade: str
    carbon_pct: float
    boron_ppm: float
    gross_mass_kg: float
    mill_cert_serial: str
    cert_status: str
    lab_report_reference: Optional[str]
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    counterfeit_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WireLot(TypedDict):
    id: str
    steel_heat_id: str
    draw_pass_count: int
    inlet_diameter_mm: float
    outlet_diameter_mm: float
    reduction_pct: float
    lubricant_coating: str
    coating_weight_gsm: float
    gross_mass_kg: float
    available_mass_kg: float
    reserved_mass_kg: float
    consumed_mass_kg: float
    status: str
    quarantine_source: str
    inspected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HeadingTool(TypedDict):
    id: str
    tool_code: str
    station_count: int
    rated_life_pieces: int
    max_regrinds: int
    regrind_count: int
    cumulative_pieces_current_cycle: int
    cycle_pieces_history: List[int]
    completed_cycle_count: int
    lifetime_pieces: int
    observed_avg_cycle_pieces: Optional[float]
    rated_derated_life_pieces: int
    conservative_life_pieces: int
    status: str
    mounted_press_code: Optional[str]
    condemn_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Furnace(TypedDict):
    id: str
    furnace_code: str
    max_charge_mass_kg: float
    cooldown_minutes: int
    status: str
    last_run_end_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionLot(TypedDict):
    id: str
    lot_code: str
    part_spec_id: str
    pinned_part_spec_version: int
    wire_lot_id: str
    heading_tool_id: str
    traceability_heat_id: str
    press_code: str
    press_window_start_at: str
    press_window_end_at: str
    planned_pieces: int
    wire_reserved_kg: float
    wire_consumed_kg: Optional[float]
    headed_count: int
    heading_scrap_count: int
    available_count: int
    scrap_count: int
    destructive_test_count: int
    packed_count: int
    tool_utilization_pct: Optional[float]
    heat_treat_completed: bool
    process_state: str
    disposition: str
    hold_source: str
    risk_score_pre_test: Optional[float]
    risk_score_final: Optional[float]
    inspection_severity: Optional[str]
    achieved_strength_class: Optional[str]
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SecondaryOperation(TypedDict):
    id: str
    production_lot_id: str
    op_type: str
    sequence_no: int
    machine_code: str
    pieces_in: int
    pieces_out: Optional[int]
    scrap_pieces: Optional[int]
    status: str
    performed_after_heat_treat: bool
    created_at: str
    updated_at: str
    version: int


class HeatTreatRun(TypedDict):
    id: str
    production_lot_id: str
    furnace_id: str
    window_start_at: str
    window_end_at: str
    austenitize_temp_c: float
    quench_medium: str
    temper_temp_c: float
    temper_time_min: int
    carbon_potential_pct: float
    charge_mass_kg: float
    core_hardness_hv: Optional[float]
    surface_decarb_depth_mm: Optional[float]
    total_decarb_depth_mm: Optional[float]
    result: str
    status: str
    started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlatingRun(TypedDict):
    id: str
    production_lot_id: str
    plating_spec: str
    load_mass_kg: float
    plated_at: Optional[str]
    bake_started_at: Optional[str]
    bake_temp_c: Optional[float]
    bake_duration_min: Optional[int]
    bake_delay_hours: Optional[float]
    bake_completed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LotTest(TypedDict):
    id: str
    production_lot_id: str
    severity: str
    sample_size: int
    acceptance_number: int
    destructive: bool
    proof_load_failures: Optional[int]
    tensile_failures: Optional[int]
    min_measured_core_hardness_hv: Optional[float]
    total_failures: Optional[int]
    result: str
    performed_by_user_id: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CertificationDocument(TypedDict):
    id: str
    production_lot_id: str
    lot_test_id: str
    cert_serial: str
    revision: int
    pinned_part_spec_version: int
    certified_strength_class: str
    traceability_chain: Dict[str, Any]
    status: str
    signed_by_user_id: Optional[str]
    issued_at: Optional[str]
    revoked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackUnit(TypedDict):
    id: str
    production_lot_id: str
    certification_document_id: str
    label_serial: str
    pack_mode: str
    net_weight_kg: Optional[float]
    actual_count: Optional[int]
    declared_count: int
    count_tolerance_pieces: int
    label_fields_complete: bool
    status: str
    sealed_at: Optional[str]
    shipped_at: Optional[str]
    recall_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


COMMON_SYSTEM_FIELDS = ["id", "created_at", "updated_at", "version"]
