"""Domain types: entity TypedDicts, status enums, role enum.

All entities carry the full common set (id, created_at, updated_at, version)
per PRD section 2.4 — "There are no exceptions in this domain".
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    SALES_REP = "SalesRep"
    PRODUCTION_PLANNER = "ProductionPlanner"
    CUSTOMER_SERVICE = "CustomerService"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    CUSTOMER = "Customer"


class Flute(str, Enum):
    B = "B"
    C = "C"
    E = "E"
    BC = "BC"


class BoardGradeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class MachineCode(str, Enum):
    CORRUGATOR = "CORRUGATOR"
    DIE_CUTTER = "DIE_CUTTER"
    FFG = "FFG"


class WorkShiftStatus(str, Enum):
    OPEN = "OPEN"
    CANCELLED = "CANCELLED"


class CorrugatorRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class RoutingType(str, Enum):
    DIE_CUT = "DIE_CUT"
    SLOTTED = "SLOTTED"


class BoardSource(str, Enum):
    INTERNAL = "INTERNAL"
    SHEET_FEEDER = "SHEET_FEEDER"


class BoxOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    QUOTED = "QUOTED"
    ACCEPTED = "ACCEPTED"
    SCHEDULED = "SCHEDULED"
    AWAITING_CONVERTING = "AWAITING_CONVERTING"
    DIE_CUT_QUEUED = "DIE_CUT_QUEUED"
    SLOTTED_QUEUED = "SLOTTED_QUEUED"
    CONVERTING = "CONVERTING"
    PRODUCED = "PRODUCED"
    INVOICED = "INVOICED"
    CANCELLED = "CANCELLED"


class PriceQuoteStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"
    INVOICED = "INVOICED"


class FreightTier(str, Enum):
    LOCAL = "LOCAL"
    REGIONAL = "REGIONAL"
    NATIONAL = "NATIONAL"


class ConvertingBookingStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InventoryProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REPLENISHMENT_NEEDED = "REPLENISHMENT_NEEDED"


class ReleaseOrderStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    TRANSIT_DAMAGE = "TRANSIT_DAMAGE"
    BOARD_WARP = "BOARD_WARP"


class QualityClaimStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_CREDIT = "RESOLVED_CREDIT"
    RESOLVED_REJECTED = "RESOLVED_REJECTED"


class CustomerAccount(TypedDict, total=False):
    id: str
    account_name: str
    ship_to_city: str
    distance_miles_from_plant: float
    credit_limit_dollars: float
    credit_exposure_dollars: float
    created_at: str
    updated_at: str
    version: int


class BoardGrade(TypedDict, total=False):
    id: str
    grade_code: str
    liner_combo: str
    flute: str
    ect_rating_lbs_per_in: int
    burst_rating_psi: int
    basis_weight_lbs_per_msf: float
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkShift(TypedDict, total=False):
    id: str
    machine_code: str
    shift_date: str
    start_minute: int
    end_minute: int
    capacity_minutes: int
    scheduled_minutes: int
    available_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CorrugatorRun(TypedDict, total=False):
    id: str
    work_shift_id: str
    board_grade_id: str
    start_minute: int
    end_minute: int
    web_width_in: float
    consumed_width_in: float
    trim_waste_in: float
    trim_waste_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BoxOrder(TypedDict, total=False):
    id: str
    customer_id: str
    board_grade_id: str
    routing_type: str
    board_source: str
    sheet_supplier_name: Optional[str]
    quantity: int
    blank_width_in: float
    blank_length_in: float
    min_ect_required: int
    ink_colors: List[str]
    color_count: int
    corrugator_run_id: Optional[str]
    area_sqft_per_box: float
    committed_value_dollars: float
    produced_qty: Optional[int]
    invoice_billable_msf: Optional[float]
    invoice_merchandise_dollars: Optional[float]
    invoice_discount_dollars: Optional[float]
    invoice_freight_dollars: Optional[float]
    invoice_total_dollars: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceQuote(TypedDict, total=False):
    id: str
    order_id: str
    unit_price_per_msf: float
    expires_on: str
    billable_msf: float
    freight_tier: str
    merchandise_total_dollars: float
    discount_pct: float
    discount_dollars: float
    freight_charge_dollars: float
    quote_total_dollars: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ConvertingBooking(TypedDict, total=False):
    id: str
    work_shift_id: str
    box_order_id: str
    start_minute: int
    end_minute: int
    ink_colors: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryProgram(TypedDict, total=False):
    id: str
    customer_id: str
    board_grade_id: str
    program_name: str
    routing_type: str
    blank_width_in: float
    blank_length_in: float
    reorder_point: int
    replenishment_qty: int
    on_hand_qty: int
    committed_qty: int
    available_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReleaseOrder(TypedDict, total=False):
    id: str
    program_id: str
    qty: int
    requested_ship_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityClaim(TypedDict, total=False):
    id: str
    box_order_id: str
    claim_type: str
    defective_qty_claimed: int
    measured_warp_pct: Optional[float]
    per_box_price_dollars: float
    provisional_credit_dollars: float
    defective_qty_verified: Optional[int]
    actual_return_freight_dollars: Optional[float]
    final_credit_dollars: Optional[float]
    filed_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
