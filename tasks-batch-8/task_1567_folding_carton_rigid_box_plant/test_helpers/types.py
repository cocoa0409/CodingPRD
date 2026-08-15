"""Domain types: entity TypedDicts, status enums, role enum.

All linear measures are integer hundredths of an inch (cin), money is integer
cents, delta-E is integer milli-units, and weight is integer grams.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    STRUCTURAL_DESIGNER = "StructuralDesigner"
    PRESS_OPERATOR = "PressOperator"
    FINISHING_OPERATOR = "FinishingOperator"
    KITTING_LEAD = "KittingLead"
    BRAND_QUALITY = "BrandQuality"
    BILLING_CLERK = "BillingClerk"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ColorStandardStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_BRAND = "PENDING_BRAND"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class SubstrateClass(str, Enum):
    COATED = "COATED"
    UNCOATED = "UNCOATED"


class JobStatus(str, Enum):
    QUOTED = "QUOTED"
    ENGINEERING = "ENGINEERING"
    PRESS_READY = "PRESS_READY"
    IN_PRODUCTION = "IN_PRODUCTION"
    FINISHING = "FINISHING"
    FINISHED = "FINISHED"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class RouteType(str, Enum):
    DIGITAL = "DIGITAL"
    OFFSET = "OFFSET"


class DesignRevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SAMPLE_MADE = "SAMPLE_MADE"
    BRAND_APPROVED = "BRAND_APPROVED"
    SUPERSEDED = "SUPERSEDED"


class ImpositionPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class NestingOrientation(str, Enum):
    NORMAL = "NORMAL"
    ROTATED = "ROTATED"


class PressApprovalStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    INVALIDATED = "INVALIDATED"


class PressType(str, Enum):
    DIGITAL = "DIGITAL"
    OFFSET = "OFFSET"


class MachineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"


class BookingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FinishingOperation(str, Enum):
    COAT = "COAT"
    FOIL = "FOIL"
    EMBOSS = "EMBOSS"


class KitOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PalletOrientation(str, Enum):
    LENGTHWISE = "LENGTHWISE"
    WIDTHWISE = "WIDTHWISE"


class AuditVerdict(str, Enum):
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class RetailAuditStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class InvoiceVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class Customer(TypedDict, total=False):
    id: str
    name: str
    brand_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ColorStandard(TypedDict, total=False):
    id: str
    customer_id: str
    ink_slot: str
    l_target: int
    a_target: int
    b_target: int
    tolerance_delta_e_milli: int
    substrate_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Job(TypedDict, total=False):
    id: str
    customer_id: str
    quantity_ordered: int
    blank_w_cin: int
    blank_h_cin: int
    grain_rotation_allowed: bool
    substrate_code: str
    caliper_pts: int
    finish_coat: bool
    finish_foil: bool
    finish_emboss: bool
    required_ink_slots: List[str]
    requires_retail_compliance: bool
    route_type: str
    status: str
    provisional_subtotal_cents: int
    provisional_total_cents: int
    board_stock_id: Optional[str]
    locked_ups: Optional[int]
    reserved_sheets: int
    sheets_consumed_actual: int
    good_sheets_actual: int
    good_cartons_actual: int
    allocated_cartons: int
    available_cartons: int
    created_at: str
    updated_at: str
    version: int


class DesignRevision(TypedDict, total=False):
    id: str
    job_id: str
    cad_ref: str
    blank_w_cin: int
    blank_h_cin: int
    grain_rotation_allowed: bool
    revision_number: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ImpositionPlan(TypedDict, total=False):
    id: str
    job_id: str
    design_revision_id: str
    sheet_w_cin: int
    sheet_h_cin: int
    gutter_cin: int
    edge_margin_cin: int
    gripper_cin: int
    ups: int
    orientation: str
    net_sheets: int
    gross_sheets: int
    layout_yield_milli_pct: int
    realized_sheets_printed: int
    realized_good_sheets: int
    realized_waste_milli_pct: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class PressApproval(TypedDict, total=False):
    id: str
    job_id: str
    color_standard_id: str
    ink_slot: str
    measured_delta_e_milli: int
    submission_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Press(TypedDict, total=False):
    id: str
    press_code: str
    press_type: str
    max_sheet_w_cin: int
    max_sheet_h_cin: int
    max_sheets_per_booking: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PressBooking(TypedDict, total=False):
    id: str
    job_id: str
    press_id: str
    planned_sheets: int
    start_utc: str
    end_utc: str
    sheets_printed: int
    sheets_good: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishingLine(TypedDict, total=False):
    id: str
    line_code: str
    supported_ops: List[str]
    setup_buffer_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FinishingBooking(TypedDict, total=False):
    id: str
    job_id: str
    line_id: str
    operation: str
    start_utc: str
    end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BoardStock(TypedDict, total=False):
    id: str
    substrate_code: str
    caliper_pts: int
    sheet_w_cin: int
    sheet_h_cin: int
    unit_cost_cents: int
    received_sheets: int
    reserved_sheets: int
    consumed_sheets: int
    available_sheets: int
    created_at: str
    updated_at: str
    version: int


class KitOrder(TypedDict, total=False):
    id: str
    job_id: str
    kit_name: str
    components: List[Dict[str, Any]]
    kits_planned: int
    consumed_per_kit: int
    allocated_cartons: int
    kits_completed: int
    consumed_cartons: int
    labor_minutes_actual: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailReadyAudit(TypedDict, total=False):
    id: str
    job_id: str
    retailer_code: str
    orientation: str
    case_w_cin: int
    case_h_cin: int
    case_d_cin: int
    case_weight_g: int
    cases_per_layer: int
    layers: int
    case_count: int
    verdict: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    job_id: str
    variant: str
    status: str
    lines: List[Dict[str, Any]]
    subtotal_cents: int
    make_ready_waived: bool
    make_ready_line_cents: int
    minimum_recovery_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int
