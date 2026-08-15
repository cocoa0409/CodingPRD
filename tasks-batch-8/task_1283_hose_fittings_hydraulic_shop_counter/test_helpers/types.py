"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SHOP_MANAGER = "ShopManager"
    COUNTER_SALES = "CounterSales"
    SHOP_TECHNICIAN = "ShopTechnician"
    FIELD_TECHNICIAN = "FieldTechnician"
    CUSTOMER = "Customer"


class ProgramStatus(str, Enum):
    NONE = "NONE"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"


class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"
    NON_COMPLIANT = "NON_COMPLIANT"


class ReelStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LOW = "LOW"
    DEPLETED = "DEPLETED"
    RETIRED = "RETIRED"


class AssemblyOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    BUILT = "BUILT"
    TEST_PASSED = "TEST_PASSED"
    TEST_FAILED = "TEST_FAILED"
    REWORK = "REWORK"
    TAGGED = "TAGGED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class DispatchStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class TestResult(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class Customer(TypedDict, total=False):
    id: str
    name: str
    credit_hold: bool
    program_enrolled: bool
    program_discount_pct: float
    inspection_interval_days: int
    compliance_score_strict: float
    compliance_score_projected: float
    program_status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict, total=False):
    id: str
    customer_id: str
    asset_tag: str
    machine_type: str
    installed_at: Optional[str]
    status: str
    installed_assembly_order_id: Optional[str]
    last_passed_inspection_at: Optional[str]
    next_due_date: Optional[str]
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Reel(TypedDict, total=False):
    id: str
    hose_sku: str
    hose_diameter_in: float
    working_pressure_psi: int
    price_per_meter_cents: int
    initial_length_mm: int
    remaining_length_mm: int
    scrap_length_mm: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Coupling(TypedDict, total=False):
    id: str
    coupling_sku: str
    size_in: float
    unit_price_cents: int
    initial_on_hand_qty: int
    on_hand_qty: int
    reserved_qty: int
    available_qty: int
    created_at: str
    updated_at: str
    version: int


class AssemblyOrder(TypedDict, total=False):
    id: str
    customer_id: str
    reel_id: str
    equipment_asset_id: Optional[str]
    cut_length_mm: int
    required_working_pressure_psi: int
    crimp_diameter_spec_mm: float
    crimp_tolerance_mm: float
    crimp_count: int
    estimated_labor_minutes: int
    is_emergency: bool
    application_error_suspected: bool
    waiver_signed: bool
    waiver_signed_by: Optional[str]
    waiver_liability_cents: Optional[int]
    measured_crimp_diameter_mm: Optional[float]
    actual_labor_minutes: Optional[int]
    test_pressure_psi: Optional[int]
    test_result: Optional[str]
    tag_serial: Optional[str]
    scrap_charged_mm: int
    status: str
    material_hose_cents: int
    material_couplings_cents: int
    waste_surcharge_cents: int
    quoted_total_cents: int
    final_total_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class AssemblyLine(TypedDict, total=False):
    # Append-only: carries only id + created_at (no updated_at, no version).
    id: str
    assembly_order_id: str
    coupling_id: str
    quantity: int
    unit_price_cents: int
    line_total_cents: int
    created_at: str


class Inspection(TypedDict, total=False):
    id: str
    equipment_asset_id: str
    inspector_name: Optional[str]
    scheduled_window_start: str
    scheduled_window_end: str
    status: str
    result: Optional[str]
    performed_at: Optional[str]
    was_overdue: bool
    created_at: str
    updated_at: str
    version: int


class ServiceDispatch(TypedDict, total=False):
    id: str
    customer_id: str
    equipment_asset_id: Optional[str]
    van_id: str
    window_start: str
    window_end: str
    status: str
    installed_assembly_order_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
