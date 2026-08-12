"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.9, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    DEALER = "Dealer"
    ENGINEER = "Engineer"
    FINISH_SUPERVISOR = "FinishSupervisor"
    PRODUCTION_PLANNER = "ProductionPlanner"
    SHIPPING_COORDINATOR = "ShippingCoordinator"


class PriceLevel(str, Enum):
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"
    L4 = "L4"
    L5 = "L5"


class Construction(str, Enum):
    SLAB = "SLAB"
    SHAKER = "SHAKER"
    RAISED_PANEL = "RAISED_PANEL"
    GLASS = "GLASS"


class Sheen(str, Enum):
    MATTE = "MATTE"
    SATIN = "SATIN"
    SEMI_GLOSS = "SEMI_GLOSS"
    HIGH_GLOSS = "HIGH_GLOSS"


class ComponentKind(str, Enum):
    SHEET_GOODS = "SHEET_GOODS"
    DOOR_BLANK = "DOOR_BLANK"
    HARDWARE = "HARDWARE"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_PRODUCTION = "IN_PRODUCTION"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class HoldStatus(str, Enum):
    NONE = "NONE"
    ON_HOLD = "ON_HOLD"


class LineType(str, Enum):
    BOX = "BOX"
    DOOR = "DOOR"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    QUOTED = "QUOTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class ModCode(str, Enum):
    REDUCED_DEPTH = "REDUCED_DEPTH"
    INCREASED_DEPTH = "INCREASED_DEPTH"
    REDUCED_WIDTH = "REDUCED_WIDTH"
    INCREASED_WIDTH = "INCREASED_WIDTH"
    TOE_KICK_NOTCH = "TOE_KICK_NOTCH"
    CUSTOM_BORE = "CUSTOM_BORE"


class ModificationStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REQUEST_CHANGES = "REQUEST_CHANGES"
    REJECT = "REJECT"


class FinishBatchStatus(str, Enum):
    MIXING = "MIXING"
    RELEASED = "RELEASED"
    FAILED = "FAILED"


class NestingRunStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class SubLotStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class ClaimType(str, Enum):
    FREIGHT_DAMAGE = "FREIGHT_DAMAGE"
    MANUFACTURING_DEFECT = "MANUFACTURING_DEFECT"
    DEALER_ERROR = "DEALER_ERROR"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED_NO_CHARGE = "APPROVED_NO_CHARGE"
    APPROVED_CHARGED = "APPROVED_CHARGED"
    DENIED = "DENIED"


class AdjudicationDecision(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    DISPATCHED = "DISPATCHED"


class HoldReason(str, Enum):
    COMPONENT_SHORTAGE = "COMPONENT_SHORTAGE"
    FINISH_QC = "FINISH_QC"


class OrderHoldStatus(str, Enum):
    PLACED = "PLACED"
    RELEASED = "RELEASED"


class PartKind(str, Enum):
    DOOR_BLANK = "DOOR_BLANK"


class Dealer(TypedDict, total=False):
    id: str
    name: str
    dealer_code: str
    price_level: str
    credit_limit_cents: int
    created_at: str
    updated_at: str
    version: int


class DoorStyle(TypedDict, total=False):
    id: str
    style_code: str
    name: str
    construction: str
    base_list_price_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class FinishSpec(TypedDict, total=False):
    id: str
    finish_code: str
    color_name: str
    sheen: str
    upcharge_pct: float
    delta_e_tolerance: float
    active: bool
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict, total=False):
    id: str
    sku: str
    description: str
    kind: str
    sheet_width_in: Optional[int]
    sheet_height_in: Optional[int]
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    reorder_level: int
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    dealer_id: str
    price_level_snapshot: str
    status: str
    hold_status: str
    cube_ft: float
    provisional_merchandise_cents: Optional[int]
    provisional_discount_cents: Optional[int]
    provisional_total_cents: Optional[int]
    final_merchandise_cents: Optional[int]
    final_discount_cents: Optional[int]
    freight_cents: Optional[int]
    grand_total_cents: Optional[int]
    delivery_route_id: Optional[str]
    route_stop_seq: Optional[int]
    submitted_at: Optional[str]
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    line_type: str
    door_style_id: Optional[str]
    finish_id: str
    width_in: int
    height_in: int
    depth_in: int
    qty: int
    unit_list_price_cents: int
    finish_upcharge_pct_snapshot: float
    line_list_cents: int
    finish_upcharge_cents: int
    mod_surcharge_cents: int
    provisional_net_cents: Optional[int]
    final_net_cents: Optional[int]
    finish_batch_id: Optional[str]
    required_sheen_lot_no: Optional[str]
    status: str
    slotted_qty: int
    created_at: str
    updated_at: str
    version: int


class ModificationRequest(TypedDict, total=False):
    id: str
    order_line_id: str
    mod_code: str
    new_dimension_in: int
    surcharge_cents: int
    revision: int
    status: str
    reviewer_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinishBatch(TypedDict, total=False):
    id: str
    finish_id: str
    sheen_lot_no: str
    capacity_doors: int
    measured_delta_e: Optional[float]
    assigned_door_count: int
    remix_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NestingStation(TypedDict, total=False):
    id: str
    station_code: str
    changeover_minutes: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class NestingRun(TypedDict, total=False):
    id: str
    station_id: str
    sheet_component_id: str
    door_line_ids: List[str]
    scheduled_date: str
    start_minute: int
    end_minute: int
    status: str
    total_blank_area_in2: Optional[int]
    sheets_required: Optional[int]
    utilization_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Part(TypedDict, total=False):
    # Append-only generated record: carries ONLY id + created_at plus the
    # generated fields. NO updated_at, NO version (PRD §2.4).
    id: str
    nesting_run_id: str
    order_line_id: str
    component_id: str
    part_kind: str
    width_in: int
    height_in: int
    qty: int
    part_seq: int
    created_at: str


class AssemblyLine(TypedDict, total=False):
    id: str
    line_code: str
    capacity_minutes_per_day: int
    standard_minutes_per_box: int
    setup_minutes_per_sub_lot: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class SubLot(TypedDict, total=False):
    id: str
    order_id: str
    order_line_id: str
    assembly_line_id: str
    scheduled_date: str
    start_minute: int
    qty: int
    work_minutes: int
    end_minute: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplacementClaim(TypedDict, total=False):
    id: str
    dealer_id: str
    original_order_line_id: str
    claim_type: str
    qty: int
    credit_basis_cents: int
    provisional_credit_cents: int
    final_credit_cents: Optional[int]
    replacement_charge_cents: Optional[int]
    status: str
    adjudicator_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryRoute(TypedDict, total=False):
    id: str
    route_code: str
    route_date: str
    capacity_cu_ft: float
    reserved_cu_ft: float
    assigned_order_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrderHold(TypedDict, total=False):
    id: str
    order_id: str
    component_id: Optional[str]
    reason: str
    shortfall_qty: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
