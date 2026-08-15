"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    LINE_SCHEDULER = "LineScheduler"
    PROCESS_CHEMIST = "ProcessChemist"
    QC_INSPECTOR = "QcInspector"
    QUALITY_MANAGER = "QualityManager"


class CoatingSpecStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class PaintLinePosture(str, Enum):
    RUNNING = "RUNNING"
    CHEM_HOLD = "CHEM_HOLD"


class PretreatmentStageStatus(str, Enum):
    IN_RANGE = "IN_RANGE"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    ADJUSTING = "ADJUSTING"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUEUED = "QUEUED"
    SCHEDULED = "SCHEDULED"
    ON_LINE = "ON_LINE"
    CURING = "CURING"
    CURE_FAILED = "CURE_FAILED"
    QC_PENDING = "QC_PENDING"
    QC_HOLD = "QC_HOLD"
    STRIPPING = "STRIPPING"
    RELEASED = "RELEASED"
    SCRAPPED = "SCRAPPED"
    CANCELLED = "CANCELLED"


class RunSlotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OvenCycleVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class QualityTestType(str, Enum):
    ADHESION = "ADHESION"
    IMPACT = "IMPACT"


class QualityTestVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class ReworkOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"


class VocPermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXCEEDED = "EXCEEDED"
    CLOSED = "CLOSED"


class EmissionSourceType(str, Enum):
    PAINT_USAGE_METERED = "PAINT_USAGE_METERED"
    PURGE_SOLVENT = "PURGE_SOLVENT"
    STRIP_SOLVENT = "STRIP_SOLVENT"
    CLOSEOUT_ADJUSTMENT = "CLOSEOUT_ADJUSTMENT"


class EmissionEntryVariant(str, Enum):
    METERED = "METERED"
    THEORETICAL = "THEORETICAL"
    ADJUSTMENT = "ADJUSTMENT"


class AllocationPolicy(str, Enum):
    FULL_TO_NEXT_LOT = "FULL_TO_NEXT_LOT"
    PRO_RATA_BY_PARTS = "PRO_RATA_BY_PARTS"


# --- Mutable resources: carry id + created_at + updated_at + version (PRD §2.4) ---


class Customer(TypedDict, total=False):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class CoatingSpec(TypedDict, total=False):
    id: str
    customer_id: str
    color_code: str
    film_build_min_um: float
    film_build_max_um: float
    cure_metal_temp_c: float
    cure_minutes_at_temp: int
    adhesion_class_min: int
    impact_joules_min: float
    voc_g_per_l: float
    area_dm2_per_part: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PaintLine(TypedDict, total=False):
    id: str
    name: str
    current_color_code: str
    line_speed_fpm: float
    hanger_capacity_parts: int
    allocation_policy: str
    posture: str
    created_at: str
    updated_at: str
    version: int


class CureOven(TypedDict, total=False):
    id: str
    name: str
    max_loads: int
    created_at: str
    updated_at: str
    version: int


class PretreatmentStage(TypedDict, total=False):
    id: str
    paint_line_id: str
    stage_name: str
    sequence_no: int
    chemical_family: str
    conc_min_gpl: float
    conc_max_gpl: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    customer_id: str
    spec_id: str
    part_quantity: int
    scrapped_quantity: int
    passed_quantity: int
    outstanding_quantity: int
    rework_count: int
    status: str
    base_charge_cents: int
    purge_alloc_cents: int
    rework_charge_cents: int
    total_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class RunSlot(TypedDict, total=False):
    id: str
    paint_line_id: str
    lot_id: str
    start_utc: str
    end_utc: str
    parts_per_hanger: int
    planned_line_speed_fpm: float
    predicted_film_build_um: float
    voc_projected_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ReworkOrder(TypedDict, total=False):
    id: str
    lot_id: str
    parts_to_rework: int
    status: str
    strip_cost_cents: int
    repaint_charge_cents: int
    scrapped_quantity: int
    total_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class VocPermit(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    cap_kg: float
    used_kg: float
    reserved_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Event records: append-only, carry ONLY id + created_at (PRD §2.4) ---


class TitrationReading(TypedDict, total=False):
    id: str
    stage_id: str
    measured_conc_gpl: float
    recorded_by_user_id: str
    in_range: bool
    created_at: str


class OvenCycle(TypedDict, total=False):
    id: str
    lot_id: str
    oven_id: str
    recheck_of_id: Optional[str]
    entered_at: str
    exited_at: str
    min_metal_temp_c: float
    minutes_at_or_above_temp: int
    verdict: str
    created_at: str


class QualityTest(TypedDict, total=False):
    id: str
    lot_id: str
    test_type: str
    measured_value: float
    recorded_by_user_id: str
    verdict: str
    created_at: str


class ColorChange(TypedDict, total=False):
    id: str
    paint_line_id: str
    from_color_code: str
    to_color_code: str
    window_start_utc: str
    window_end_utc: str
    purge_solvent_liters: float
    purge_cost_cents: int
    purge_voc_kg: float
    allocation_method: str
    created_at: str


class EmissionEntry(TypedDict, total=False):
    id: str
    permit_id: str
    source_type: str
    source_lot_id: Optional[str]
    source_color_change_id: Optional[str]
    voc_kg: float
    entry_variant: str
    created_at: str
