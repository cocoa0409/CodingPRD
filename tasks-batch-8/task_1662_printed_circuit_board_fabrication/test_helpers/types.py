"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, List, Optional, TypedDict


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    SALES_ENGINEER = "SalesEngineer"
    CAM_OPERATOR = "CAMOperator"
    PROCESS_ENGINEER = "ProcessEngineer"
    QUALITY_INSPECTOR = "QualityInspector"
    PRODUCTION_PLANNER = "ProductionPlanner"
    FAB_ADMIN = "FabAdmin"


class FabStatus(str, Enum):
    QUOTED = "QUOTED"
    DFM_REVIEW = "DFM_REVIEW"
    AWAITING_LAMINATE = "AWAITING_LAMINATE"
    RELEASED = "RELEASED"
    IN_PRODUCTION = "IN_PRODUCTION"
    ON_HOLD = "ON_HOLD"
    AWAITING_ETEST = "AWAITING_ETEST"
    COMPLETED = "COMPLETED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class QualityDisposition(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CONDITIONAL = "CONDITIONAL"


class StackupStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class PanelArrayStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class DrillProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QUALIFIED = "QUALIFIED"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    QUARANTINED = "QUARANTINED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class CouponStatus(str, Enum):
    AWAITING_MEASURE = "AWAITING_MEASURE"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class EtestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"
    CANCELLED = "CANCELLED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"


class MaterialCode(str, Enum):
    FR4_TG135 = "FR4_TG135"
    FR4_TG170 = "FR4_TG170"
    ROGERS_4350 = "ROGERS_4350"


class ServiceLane(str, Enum):
    STANDARD = "STANDARD"
    QUICK_TURN = "QUICK_TURN"


class SurfaceFinish(str, Enum):
    HASL = "HASL"
    OSP = "OSP"
    ENIG = "ENIG"
    IMMERSION_SILVER = "IMMERSION_SILVER"
    HARD_GOLD = "HARD_GOLD"


class LineType(str, Enum):
    SINGLE_ENDED = "SINGLE_ENDED"
    DIFFERENTIAL = "DIFFERENTIAL"


class DispositionBasis(str, Enum):
    SINGLE = "SINGLE"
    STATISTICAL = "STATISTICAL"


class MeasurementResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DefectCode(str, Enum):
    OPEN = "OPEN"
    SHORT = "SHORT"
    SPACING = "SPACING"
    DRILL_BREAKOUT = "DRILL_BREAKOUT"
    PLATING_VOID = "PLATING_VOID"
    SOLDERMASK = "SOLDERMASK"
    CONTAMINATION = "CONTAMINATION"
    OVERETCH = "OVERETCH"
    IMPEDANCE = "IMPEDANCE"


class DefectSeverity(str, Enum):
    COSMETIC = "COSMETIC"
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SCRAP = "SCRAP"


class DefectSource(str, Enum):
    AOI = "AOI"
    MANUAL = "MANUAL"
    ETEST = "ETEST"


class LabStation(str, Enum):
    MICROSECTION_A = "MICROSECTION_A"


# --- Entity TypedDicts ---
# Most resources carry id + created_at + updated_at + version (PRD §2.4).
# CouponMeasurement and DefectRecord are append-only: only id + created_at.


class Customer(TypedDict, total=False):
    id: str
    company_name: str
    contact_email: str
    credit_limit_cents: int
    tax_exempt: bool
    created_at: str
    updated_at: str
    version: int


class QuickTurnLane(TypedDict, total=False):
    id: str
    lane_code: str
    turn_days: int
    capacity_boards_per_day: int
    premium_multiplier: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class LaminateLot(TypedDict, total=False):
    id: str
    material_code: str
    lot_code: str
    manufacture_date: str
    panels_total: int
    panels_reserved: int
    panels_consumed: int
    panels_available: int
    expiry_date: str
    status: str
    qualified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FabOrder(TypedDict, total=False):
    id: str
    customer_id: str
    order_number: str
    service_lane: str
    quick_turn_lane_id: Optional[str]
    board_x_mils: int
    board_y_mils: int
    layer_count: int
    surface_finish: str
    quantity_boards: int
    requested_ship_date: str
    fab_status: str
    quality_disposition: str
    boards_scrapped: int
    laminate_lot_codes: List[str]
    provisional_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Stackup(TypedDict, total=False):
    id: str
    fab_order_id: str
    revision: int
    total_thickness_mils: float
    dielectric_material: str
    copper_weight_oz: int
    impedance_controlled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpedanceSpecLine(TypedDict, total=False):
    id: str
    stackup_id: str
    layer_name: str
    target_ohms: float
    tolerance_plus_ohms: float
    tolerance_minus_ohms: float
    line_type: str
    coupon_required: bool
    created_at: str
    updated_at: str
    version: int


class PanelArray(TypedDict, total=False):
    id: str
    fab_order_id: str
    array_x: int
    array_y: int
    panel_width_mils: int
    panel_height_mils: int
    boards_per_panel: int
    array_yield: float
    good_boards_per_panel: int
    panels_required: int
    utilization_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class DrillProgram(TypedDict, total=False):
    id: str
    fab_order_id: str
    revision: int
    min_hole_mils: float
    hole_count: int
    plated_aspect_ratio: float
    created_by_user_id: str
    rejection_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LaminateReservation(TypedDict, total=False):
    id: str
    fab_order_id: str
    panel_array_id: str
    laminate_lot_id: str
    panels_allocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class LaneSlotCommitment(TypedDict, total=False):
    id: str
    lane_id: str
    ship_date: str
    committed_boards: int
    created_at: str
    updated_at: str
    version: int


class ImpedanceCoupon(TypedDict, total=False):
    id: str
    fab_order_id: str
    spec_line_id: str
    panel_ref: str
    status: str
    retest_count: int
    latest_measured_ohms: Optional[float]
    disposition_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CouponMeasurement(TypedDict, total=False):
    # Append-only (PRD §2.4): carries only id + created_at, no updated_at/version.
    id: str
    coupon_id: str
    lab_slot_booking_id: str
    measured_ohms: float
    measured_ohms_b: Optional[float]
    measured_at: str
    result: str
    created_at: str


class LabSlotBooking(TypedDict, total=False):
    id: str
    coupon_id: str
    station: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ElecTestRun(TypedDict, total=False):
    id: str
    fab_order_id: str
    fixture_id: str
    test_voltage: float
    status: str
    boards_tested: int
    boards_failed: int
    opens_found: int
    shorts_found: int
    created_at: str
    updated_at: str
    version: int


class DefectRecord(TypedDict, total=False):
    # Append-only (PRD §2.4): carries only id + created_at, no updated_at/version.
    id: str
    fab_order_id: str
    panel_array_id: str
    defect_code: str
    severity: str
    boards_affected: int
    detected_at: str
    source: str
    created_at: str


class Invoice(TypedDict, total=False):
    id: str
    fab_order_id: str
    actual_panels_run: int
    line_items: List[Any]
    retest_fees_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
