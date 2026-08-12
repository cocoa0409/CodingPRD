"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Status enums ─────────────────────────────────────────────────────

class ProductModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class CustomerOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    MATERIAL_HOLD = "MATERIAL_HOLD"
    IN_PRODUCTION = "IN_PRODUCTION"
    QUALITY_REVIEW = "QUALITY_REVIEW"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    MATERIAL_SHORTFALL = "MATERIAL_SHORTFALL"
    ALLOCATED = "ALLOCATED"
    CUT = "CUT"
    SEWN = "SEWN"
    UPHOLSTERED = "UPHOLSTERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class MaterialLotStatus(str, Enum):
    EXPECTED = "EXPECTED"
    RECEIVED = "RECEIVED"
    AVAILABLE = "AVAILABLE"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"
    RETURNED = "RETURNED"


class MaterialAllocationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class CutPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    CUT = "CUT"
    SUPERSEDED = "SUPERSEDED"
    VOID = "VOID"


class CellStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DOWN = "DOWN"


class CellBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    RELEASED = "RELEASED"


class ComplianceCertificateStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    VOID = "VOID"


class SupplyRequisitionStatus(str, Enum):
    OPEN = "OPEN"
    PLACED = "PLACED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class ShowroomSampleDisposition(str, Enum):
    ON_LOAN = "ON_LOAN"
    RETURNED = "RETURNED"
    SOLD = "SOLD"
    WRITTEN_OFF = "WRITTEN_OFF"


class ShipmentStatus(str, Enum):
    DRAFT = "DRAFT"
    RATED = "RATED"
    TENDERED = "TENDERED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"


class UserRole(str, Enum):
    SALES_REP = "SalesRep"
    PRODUCTION_PLANNER = "ProductionPlanner"
    MATERIAL_RECEIVER = "MaterialReceiver"
    QUALITY_INSPECTOR = "QualityInspector"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SHIPPING_COORDINATOR = "ShippingCoordinator"
    PLANT_ADMIN = "PlantAdmin"


# ─── Entity TypedDicts (all entities carry the four standard fields) ──


class ProductModel(TypedDict, total=False):
    id: str
    model_code: str
    category: str
    base_fabric_yards: float
    base_price_cents: int
    requires_pattern_match: bool
    flammability_standard: str
    required_component_codes: List[str]
    option_rules: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class FabricSpec(TypedDict, total=False):
    id: str
    fabric_code: str
    origin: str
    grade: str
    nominal_width_inches: float
    pattern_repeat_v_inches: float
    pattern_repeat_h_inches: float
    match_method: str
    price_per_yard_cents: int
    com_credit_per_yard_cents: int
    created_at: str
    updated_at: str
    version: int


class DealerAccount(TypedDict, total=False):
    id: str
    dealer_code: str
    name: str
    credit_limit_cents: int
    sample_allowance_cents: int
    outstanding_sample_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict, total=False):
    id: str
    order_number: str
    dealer_id: str
    ship_to_state: str
    delivery_method: str
    status: str
    common_flammability_standard: Optional[str]
    subtotal_cents: int
    com_credit_cents: int
    total_cents: int
    quality_result: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    model_id: str
    fabric_spec_id: str
    fabric_source: str
    finish_code: str
    quantity: int
    matched_surcharge_pct: float
    unit_price_cents: int
    line_total_cents: int
    required_yards_provisional: Optional[float]
    required_yards_final: Optional[float]
    allocated_yards: float
    shortfall_yards: float
    status: str
    created_at: str
    updated_at: str
    version: int


class MaterialLot(TypedDict, total=False):
    id: str
    fabric_spec_id: str
    order_line_id: Optional[str]
    parent_lot_id: Optional[str]
    ownership: str
    expected_yards: float
    received_yards: Optional[float]
    measured_width_inches: Optional[float]
    usable_yards: Optional[float]
    rejected_yards: Optional[float]
    allocated_yards: float
    available_yards: float
    status: str
    received_at: Optional[str]
    inspected_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialAllocation(TypedDict, total=False):
    id: str
    lot_id: str
    order_line_id: str
    yards: float
    consumed_yards: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CutPlan(TypedDict, total=False):
    id: str
    order_line_id: str
    marker_length_yards: Optional[float]
    required_yards_final: Optional[float]
    utilization_pct: Optional[float]
    waste_yards: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Cell(TypedDict, total=False):
    id: str
    cell_code: str
    cell_type: str
    capacity_slots: int
    certifications: List[str]
    committed_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CellBooking(TypedDict, total=False):
    id: str
    cell_id: str
    order_line_id: str
    operation: str
    start_at: str
    end_at: str
    duration_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceCertificate(TypedDict, total=False):
    id: str
    order_id: str
    standard: str
    label_lot_number: str
    label_count: int
    created_by: str
    certified_by: Optional[str]
    certified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SupplyRequisition(TypedDict, total=False):
    id: str
    order_line_id: str
    component_code: str
    quantity: int
    source_type: str
    ordered_quantity: int
    unit_cost_cents: int
    extended_cost_cents: int
    available_date: str
    status: str
    received_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShowroomSample(TypedDict, total=False):
    id: str
    dealer_id: str
    model_id: str
    unit_serial: str
    sample_value_cents: int
    due_back_days: int
    loaned_at: str
    due_back_at: str
    returned_at: Optional[str]
    disposition: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    order_id: str
    carrier_name: str
    method: str
    weight_lb: float
    length_in: float
    width_in: float
    height_in: float
    declared_value_cents: int
    piece_count: int
    density_lb_per_cuft: Optional[float]
    freight_class: Optional[str]
    freight_charge_cents: Optional[int]
    condition_check_passed: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int
