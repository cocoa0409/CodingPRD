"""Domain types for the carpet mill API: status enums, entity TypedDicts, role enum.

All names come from the PRD entity tables and workflow sections.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    MILL_PLANNER = "MillPlanner"
    EXTRUSION_OPERATOR = "ExtrusionOperator"
    DYE_HOUSE_OPERATOR = "DyeHouseOperator"
    QA_LAB_TECHNICIAN = "QALabTechnician"
    CERTIFICATION_OFFICER = "CertificationOfficer"
    DEALER_BUYER = "DealerBuyer"
    PLANT_ADMIN = "PlantAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    CLOSED = "CLOSED"


class AccountType(str, Enum):
    DEALER = "DEALER"
    BUILDER = "BUILDER"
    COMMERCIAL = "COMMERCIAL"


class PolymerLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class PolymerType(str, Enum):
    NYLON_6 = "NYLON_6"
    NYLON_66 = "NYLON_66"
    PET = "PET"
    POLYPROPYLENE = "POLYPROPYLENE"


class ReclaimSource(str, Enum):
    VIRGIN = "VIRGIN"
    POST_CONSUMER = "POST_CONSUMER"
    POST_INDUSTRIAL = "POST_INDUSTRIAL"


class ReclamationBatchStatus(str, Enum):
    RECEIVED = "RECEIVED"
    DEPOLYMERIZED = "DEPOLYMERIZED"


class FiberBatchStatus(str, Enum):
    QUEUED = "QUEUED"
    SPUN = "SPUN"
    RELEASED = "RELEASED"
    ALLOCATED = "ALLOCATED"
    CONSUMED = "CONSUMED"
    SCRAPPED = "SCRAPPED"


class FiberDyeMethod(str, Enum):
    SOLUTION_DYED = "SOLUTION_DYED"
    PIECE_DYED_READY = "PIECE_DYED_READY"


class StyleDyeMethod(str, Enum):
    SOLUTION_DYED = "SOLUTION_DYED"
    PIECE_DYED = "PIECE_DYED"


class LineType(str, Enum):
    RUNNING_LINE = "RUNNING_LINE"
    CUSTOM = "CUSTOM"


class GaugeCode(str, Enum):
    G_1_8 = "G_1_8"
    G_1_10 = "G_1_10"
    G_5_64 = "G_5_64"


class PileConstruction(str, Enum):
    CUT = "CUT"
    LOOP = "LOOP"


class ReplenishmentFlag(str, Enum):
    NONE = "NONE"
    REPLENISH_REQUIRED = "REPLENISH_REQUIRED"


class CarpetStyleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RUNOUT = "RUNOUT"
    DISCONTINUED = "DISCONTINUED"


class TuftingMachineStatus(str, Enum):
    IDLE = "IDLE"
    MAINTENANCE = "MAINTENANCE"


class DyeVesselType(str, Enum):
    BECK = "BECK"
    JET = "JET"


class DyeVesselStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"


class SecondaryBackingType(str, Enum):
    ACTION_BAC = "ACTION_BAC"
    WOVEN_POLYPROPYLENE = "WOVEN_POLYPROPYLENE"
    CUSHION = "CUSHION"


class ProductionRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    TUFTING = "TUFTING"
    GREIGE = "GREIGE"
    BACKED = "BACKED"
    BACKING_FAILED = "BACKING_FAILED"
    RELEASED = "RELEASED"
    ABORTED = "ABORTED"


class ShadeBand(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    OUT = "OUT"
    SOLUTION = "SOLUTION"


class DyeLotStatus(str, Enum):
    FORMULATED = "FORMULATED"
    DYEING = "DYEING"
    MEASURED = "MEASURED"
    APPROVED = "APPROVED"
    REDYE_QUEUED = "REDYE_QUEUED"
    EXHAUSTED = "EXHAUSTED"
    REJECTED = "REJECTED"


class DyeLotDisposition(str, Enum):
    APPROVE = "APPROVE"
    REDYE = "REDYE"
    REJECT = "REJECT"


class RollGoodQaStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    HELD = "HELD"
    FAILED = "FAILED"


class RollGoodInventoryStatus(str, Enum):
    IN_PROCESS = "IN_PROCESS"
    AVAILABLE = "AVAILABLE"
    COMMITTED = "COMMITTED"
    DEPLETED = "DEPLETED"
    SCRAPPED = "SCRAPPED"


class RollGoodDisposition(str, Enum):
    RELEASE = "RELEASE"
    HOLD = "HOLD"
    SCRAP = "SCRAP"


class FiberBatchDisposition(str, Enum):
    RELEASE = "RELEASE"
    SCRAP = "SCRAP"


class ProductTestType(str, Enum):
    WEAR_TARR = "WEAR_TARR"
    STAIN_AATCC175 = "STAIN_AATCC175"
    FLAMMABILITY_PILL = "FLAMMABILITY_PILL"


class ProductTestVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CertType(str, Enum):
    DOC_FF_1_70 = "DOC_FF_1_70"
    NSF_140 = "NSF_140"
    GREEN_LABEL_PLUS = "GREEN_LABEL_PLUS"


class AccountingBasis(str, Enum):
    MASS_BALANCE = "MASS_BALANCE"
    PHYSICAL_SEGREGATION = "PHYSICAL_SEGREGATION"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class CutOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    CUT = "CUT"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class OrderType(str, Enum):
    RUNNING_LINE = "RUNNING_LINE"
    CUSTOM = "CUSTOM"


class ShadeTolerance(str, Enum):
    SINGLE_LOT = "SINGLE_LOT"
    BAND_MATCH = "BAND_MATCH"
    ANY = "ANY"


class CutAllocationStatus(str, Enum):
    RESERVED = "RESERVED"
    CUT = "CUT"
    SHIPPED = "SHIPPED"
    RELEASED = "RELEASED"
    VOIDED = "VOIDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Every entity below carries id + created_at + updated_at + version, EXCEPT
# ProductTest, which the PRD singles out as carrying only id and created_at.
# ---------------------------------------------------------------------------


class Account(TypedDict):
    id: str
    account_code: str
    account_type: str
    credit_limit_cents: int
    credit_used_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PolymerLot(TypedDict):
    id: str
    lot_code: str
    polymer_type: str
    received_kg: float
    available_kg: float
    reserved_kg: float
    consumed_kg: float
    scrapped_kg: float
    recycled_content_pct: float
    segregated: bool
    reclaim_source: str
    melt_flow_index: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ReclamationBatch(TypedDict):
    id: str
    batch_code: str
    source_roll_good_id: Optional[str]
    intake_lbs: float
    face_fiber_type: str
    contamination_pct: float
    depolymerized_kg: float
    output_polymer_lot_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FiberBatch(TypedDict):
    id: str
    batch_code: str
    polymer_lot_id: str
    input_kg: float
    blend_polymer_lot_id: Optional[str]
    blend_input_kg: float
    denier_target: float
    filament_count: int
    dye_method: str
    solution_color_code: Optional[str]
    throughput_g_per_min: Optional[float]
    spin_speed_m_per_min: Optional[float]
    denier_actual: Optional[float]
    extruded_kg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarpetStyle(TypedDict):
    id: str
    style_code: str
    line_type: str
    gauge_code: str
    pile_construction: str
    pile_height_mm: float
    pattern_repeat_mm: float
    plies: int
    target_face_weight_oz: float
    dye_method: str
    solution_color_code: Optional[str]
    list_price_cents_per_yard: int
    open_backorder_yards: float
    replenishment_flag: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TuftingMachine(TypedDict):
    id: str
    machine_code: str
    native_gauge_code: str
    min_pile_height_mm: float
    max_pile_height_mm: float
    changeover_minutes: int
    needle_bar_width_in: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DyeVessel(TypedDict):
    id: str
    vessel_code: str
    vessel_type: str
    capacity_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    run_code: str
    style_id: str
    machine_id: str
    fiber_batch_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    gauge_loaded_code: Optional[str]
    pile_height_set_mm: Optional[float]
    pattern_repeat_loaded_mm: Optional[float]
    stitch_rate_per_inch: Optional[float]
    greige_yards: Optional[float]
    face_weight_oz_per_sy: Optional[float]
    sbr_pct: Optional[float]
    filler_load_pct: Optional[float]
    cure_temp_c: Optional[int]
    cure_seconds: Optional[int]
    secondary_backing_type: Optional[str]
    delamination_strength_lbf: Optional[float]
    recoat_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DyeLot(TypedDict):
    id: str
    lot_code: str
    production_run_id: str
    vessel_id: str
    parent_dye_lot_id: Optional[str]
    color_code: str
    target_lab_l: float
    target_lab_a: float
    target_lab_b: float
    measured_lab_l: Optional[float]
    measured_lab_a: Optional[float]
    measured_lab_b: Optional[float]
    delta_e: Optional[float]
    shade_band: Optional[str]
    lot_kg: float
    dye_start_utc: str
    dye_end_utc: str
    dyed_yards: float
    scrapped_yards: float
    uncommitted_yards: float
    shipped_basis_uncommitted_yards: float
    redye_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RollGood(TypedDict):
    id: str
    roll_number: str
    production_run_id: str
    dye_lot_id: Optional[str]
    parent_roll_id: Optional[str]
    width_ft: float
    initial_yards: float
    available_yards: float
    shade_band: str
    is_remnant: bool
    qa_status: str
    inventory_status: str
    created_at: str
    updated_at: str
    version: int


class ProductTest(TypedDict):
    """Append-only lab record: carries only id and created_at as system fields."""

    id: str
    style_id: str
    roll_good_id: str
    test_type: str
    result_value: float
    verdict: str
    tested_by_user_id: str
    tested_at_utc: str
    created_at: str


class Certification(TypedDict):
    id: str
    style_id: str
    cert_type: str
    accounting_basis: str
    source_test_ids: List[str]
    recorded_recycled_content_pct: Optional[float]
    certified_by_user_id: str
    issued_at_utc: str
    expires_at_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CutOrder(TypedDict):
    id: str
    order_code: str
    account_id: str
    style_id: str
    order_type: str
    requested_yards: float
    shade_tolerance: str
    allocated_yards: float
    reserved_credit_cents: int
    gross_cents: int
    freight_cents: int
    remnant_credit_cents: int
    net_invoice_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CutAllocation(TypedDict):
    id: str
    cut_order_id: str
    roll_good_id: str
    yards: float
    shade_band: str
    from_remnant: bool
    line_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
