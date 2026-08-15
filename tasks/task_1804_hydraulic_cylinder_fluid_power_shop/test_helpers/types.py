"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SHOP_ADMIN = "ShopAdmin"
    SERVICE_ADVISOR = "ServiceAdvisor"
    TECHNICIAN = "Technician"
    QUALITY_INSPECTOR = "QualityInspector"
    CUSTOMER = "Customer"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CylinderStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    EXCHANGED = "EXCHANGED"


class WorkOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    TEARDOWN = "TEARDOWN"
    QUOTE_DRAFT = "QUOTE_DRAFT"
    QUOTE_SENT = "QUOTE_SENT"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    IN_REPAIR = "IN_REPAIR"
    ASSEMBLED = "ASSEMBLED"
    TEST_PENDING = "TEST_PENDING"
    TEST_PASSED = "TEST_PASSED"
    CERTIFIED = "CERTIFIED"
    SCRAP_AUTHORIZED = "SCRAP_AUTHORIZED"
    SCRAPPED = "SCRAPPED"
    EXCHANGE_SELECTED = "EXCHANGE_SELECTED"
    EXCHANGE_FULFILLED = "EXCHANGE_FULFILLED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class QuoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SENT = "SENT"
    APPROVED = "APPROVED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED_SCRAP = "REJECTED_SCRAP"


class InventoryItemStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"


class InventoryItemOrigin(str, Enum):
    RECEIVED = "RECEIVED"
    REMNANT = "REMNANT"


class ReservationStatus(str, Enum):
    OPEN = "OPEN"
    CONSUMED = "CONSUMED"
    RELEASED = "RELEASED"


class PressureTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"
    CANCELLED = "CANCELLED"


class CertificateStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"


class ExchangeUnitStatus(str, Enum):
    IN_POOL = "IN_POOL"
    RESERVED = "RESERVED"
    FULFILLED = "FULFILLED"
    CORE_RECEIVED = "CORE_RECEIVED"
    SETTLED = "SETTLED"


class FieldServiceJobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Tier(str, Enum):
    STANDARD = "STANDARD"
    EXPEDITE = "EXPEDITE"
    EMERGENCY = "EMERGENCY"


class PressureClass(str, Enum):
    CLASS_3000 = "CLASS_3000"
    CLASS_5000 = "CLASS_5000"


class FluidType(str, Enum):
    MINERAL_OIL = "MINERAL_OIL"
    PHOSPHATE_ESTER = "PHOSPHATE_ESTER"
    WATER_GLYCOL = "WATER_GLYCOL"


class Material(str, Enum):
    CHROME_ROD = "CHROME_ROD"
    HONING_TUBE = "HONING_TUBE"


class HoseType(str, Enum):
    WIRE_BRAID_2SN = "WIRE_BRAID_2SN"
    SPIRAL_4SH = "SPIRAL_4SH"
    THERMOPLASTIC = "THERMOPLASTIC"


class CoreCondition(str, Enum):
    GOOD = "GOOD"
    WORN = "WORN"
    DAMAGED = "DAMAGED"
    SCRAP = "SCRAP"


class CoreCompleteness(str, Enum):
    COMPLETE = "COMPLETE"
    MISSING_PARTS = "MISSING_PARTS"


class TechnicianSkill(str, Enum):
    CYLINDER_REPAIR = "CYLINDER_REPAIR"
    FIELD_SERVICE = "FIELD_SERVICE"


class QuoteLineKind(str, Enum):
    SEAL_KIT = "SEAL_KIT"
    ROD = "ROD"
    TUBE = "TUBE"
    HONING = "HONING"
    LABOR = "LABOR"
    SUPPLIES = "SUPPLIES"


# --- Entity record types (all entities carry the §2.4 common fields) ---


class Shop(TypedDict, total=False):
    id: str
    name: str
    labor_rate_cents_per_hour: int
    expedite_multiplier: float
    emergency_multiplier: float
    expedite_cutoff_hours: int
    emergency_cutoff_hours: int
    honing_pass_fee_cents: int
    cut_fee_cents: int
    kerf_mm: int
    min_remnant_mm: int
    quote_ttl_hours: int
    bay_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    credit_limit_cents: int
    opening_ytd_spend_cents: int
    ytd_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict, total=False):
    id: str
    full_name: str
    skills: List[str]
    active: bool
    created_at: str
    updated_at: str
    version: int


class SealKit(TypedDict, total=False):
    id: str
    kit_code: str
    bore_min_mm: int
    bore_max_mm: int
    pressure_class_max: str
    fluid_compat: List[str]
    price_cents: int
    material: str
    created_at: str
    updated_at: str
    version: int


class Cylinder(TypedDict, total=False):
    id: str
    customer_id: str
    serial_number: str
    bore_mm: int
    stroke_mm: int
    rod_diameter_mm: int
    pressure_class: str
    fluid_type: str
    seal_kit_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    cylinder_id: str
    customer_id: str
    tier: str
    promised_hours: int
    complaint: str
    status: str
    assigned_technician_id: Optional[str]
    actual_labor_hours: Optional[float]
    latest_cleanliness_code4: Optional[int]
    latest_cleanliness_code6: Optional[int]
    latest_cleanliness_code14: Optional[int]
    cleanliness_passed: bool
    final_total_cents: Optional[int]
    invoice_total_cents: Optional[int]
    core_credit_applied_cents: int
    created_at: str
    updated_at: str
    version: int


class TeardownReport(TypedDict, total=False):
    id: str
    work_order_id: str
    rod_needed: bool
    rod_cut_length_mm: Optional[int]
    tube_needed: bool
    tube_cut_length_mm: Optional[int]
    honing_passes: int
    seal_kit_id: Optional[str]
    estimated_labor_hours: float
    findings_notes: str
    created_at: str
    updated_at: str
    version: int


class Quote(TypedDict, total=False):
    id: str
    work_order_id: str
    teardown_report_id: str
    pinned_teardown_version: int
    tier_snapshot: str
    status: str
    line_items: List[Dict[str, Any]]
    provisional_total_cents: int
    sent_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict, total=False):
    id: str
    material: str
    diameter_mm: int
    length_mm: int
    cost_per_mm_cents: int
    status: str
    origin: str
    created_at: str
    updated_at: str
    version: int


class StockReservation(TypedDict, total=False):
    id: str
    work_order_id: str
    inventory_item_id: str
    material: str
    diameter_mm: int
    cut_length_mm: int
    kerf_mm: int
    scrap_length_mm: int
    scrap_charge_cents: int
    consumed_length_mm: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TestBay(TypedDict, total=False):
    id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class PressureTest(TypedDict, total=False):
    id: str
    work_order_id: str
    test_bay_id: str
    window_start: str
    window_end: str
    required_hold_psi: int
    measured_hold_psi: Optional[int]
    duration_min: Optional[int]
    leakage_drops: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    work_order_id: str
    pressure_test_id: str
    issued_by: str
    status: str
    revoke_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExchangeUnit(TypedDict, total=False):
    id: str
    bore_mm: int
    stroke_mm: int
    rod_diameter_mm: int
    pressure_class: str
    unit_price_cents: int
    status: str
    work_order_id: Optional[str]
    provisional_credit_cents: Optional[int]
    condition: Optional[str]
    completeness: Optional[str]
    final_credit_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FieldServiceJob(TypedDict, total=False):
    id: str
    customer_id: str
    site_address: str
    distance_km: int
    assemblies: List[Dict[str, Any]]
    technician_id: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    emergency_callout: bool
    provisional_price_cents: int
    final_price_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
