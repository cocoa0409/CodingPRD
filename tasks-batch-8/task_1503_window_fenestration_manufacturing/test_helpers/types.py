"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    DEALER_REP = "DealerRep"
    PLANT_ENGINEER = "PlantEngineer"
    PRODUCTION_LEAD = "ProductionLead"
    SHIPPING_COORDINATOR = "ShippingCoordinator"
    WARRANTY_ADJUSTER = "WarrantyAdjuster"
    PLANT_MANAGER = "PlantManager"


class CreditStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"


class SeriesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class FrameMaterial(str, Enum):
    VINYL = "VINYL"
    WOOD = "WOOD"
    ALUMINUM_CLAD = "ALUMINUM_CLAD"
    FIBERGLASS = "FIBERGLASS"


class SpacerType(str, Enum):
    ALUMINUM = "ALUMINUM"
    WARM_EDGE = "WARM_EDGE"


class Shape(str, Enum):
    RECTANGLE = "RECTANGLE"
    ARCH = "ARCH"
    CIRCLE = "CIRCLE"
    TRAPEZOID = "TRAPEZOID"


class GridStyle(str, Enum):
    NONE = "NONE"
    COLONIAL = "COLONIAL"
    PRAIRIE = "PRAIRIE"
    DIAMOND = "DIAMOND"


class HardwareFinish(str, Enum):
    STANDARD = "STANDARD"
    BRUSHED_NICKEL = "BRUSHED_NICKEL"
    OIL_RUBBED_BRONZE = "OIL_RUBBED_BRONZE"


class OrderProductionStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class OrderComplianceStatus(str, Enum):
    PENDING = "PENDING"
    PROVISIONALLY_COMPLIANT = "PROVISIONALLY_COMPLIANT"
    CERTIFIED = "CERTIFIED"


class OrderLineStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"
    IN_PRODUCTION = "IN_PRODUCTION"
    GLASS_HOLD = "GLASS_HOLD"
    COMPLETED = "COMPLETED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class LabelBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


class LabelCompliance(str, Enum):
    UNEVALUATED = "UNEVALUATED"
    PASS = "PASS"
    FAIL = "FAIL"


class IGUnitStatus(str, Enum):
    QUEUED = "QUEUED"
    GLASS_CUT = "GLASS_CUT"
    SEALED = "SEALED"
    GAS_FILLED = "GAS_FILLED"
    QC_PASSED = "QC_PASSED"
    BROKEN = "BROKEN"
    SCRAPPED = "SCRAPPED"


class BreakCause(str, Enum):
    HANDLING = "HANDLING"
    LAMINATION_DEFECT = "LAMINATION_DEFECT"
    SEAL_FAILURE = "SEAL_FAILURE"
    SHIPPING_DAMAGE = "SHIPPING_DAMAGE"
    GAS_NONCOMPLIANCE = "GAS_NONCOMPLIANCE"


class WaveStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class RackStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    BOOKED = "BOOKED"


class ReservationStatus(str, Enum):
    RESERVED = "RESERVED"
    LOADING = "LOADING"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class ClaimComponent(str, Enum):
    FRAME = "FRAME"
    IG_SEAL = "IG_SEAL"
    GLASS = "GLASS"
    HARDWARE = "HARDWARE"
    GRID = "GRID"


class CoverageVariant(str, Enum):
    COMPONENT = "COMPONENT"
    WHOLE_UNIT = "WHOLE_UNIT"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    FULFILLED = "FULFILLED"
    CLOSED = "CLOSED"


class Remedy(str, Enum):
    REPAIR_PART = "REPAIR_PART"
    REFUND = "REFUND"


class Carrier(str, Enum):
    PARCEL = "PARCEL"
    STANDARD_FREIGHT = "STANDARD_FREIGHT"
    EXPEDITED = "EXPEDITED"


class ShipmentStatus(str, Enum):
    PICKING = "PICKING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


# --- Entity TypedDicts (all carry the common fields of PRD §2.4) ---


class Dealer(TypedDict):
    id: str
    name: str
    ship_to_state_code: str
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class CatalogSeries(TypedDict):
    id: str
    series_code: str
    frame_material: str
    base_rate_cents_per_ui: int
    min_billable_sqft: float
    max_united_inches: int
    special_shape_upcharge_pct: int
    lead_time_standard_days: int
    lead_time_special_shape_days: int
    frame_warranty_years: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GlassPackage(TypedDict):
    id: str
    code: str
    pane_count: int
    spacer_type: str
    argon_target_pct: int
    argon_min_pct: int
    catalog_u_factor: float
    catalog_shgc: float
    price_per_sqft_cents: int
    ig_warranty_years: int
    created_at: str
    updated_at: str
    version: int


class EnergyCodeRule(TypedDict):
    id: str
    state_code: str
    max_u_factor: float
    max_shgc: float
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WindowOrder(TypedDict):
    id: str
    dealer_id: str
    ship_to_state_code: str
    order_date: str
    production_status: str
    compliance_status: str
    wave_id: Optional[str]
    promised_date: Optional[str]
    subtotal_cents: int
    discount_cents: int
    total_price_cents: int
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict):
    id: str
    order_id: str
    series_id: str
    glass_package_id: str
    shape: str
    width_in: float
    height_in: float
    quantity: int
    grid_style: str
    hardware_finish: str
    united_inches: float
    glazing_sqft: float
    billable_sqft: float
    lead_time_days: int
    line_total_cents: int
    status: str
    rack_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnergyLabel(TypedDict):
    id: str
    order_line_id: str
    basis: str
    u_factor: float
    shgc: float
    applied_energy_code_rule_id: Optional[str]
    compliance: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IGUnit(TypedDict):
    id: str
    order_line_id: str
    unit_index: int
    remake_of_id: Optional[str]
    spacer_type: str
    argon_measured_pct: Optional[int]
    break_cause: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionWave(TypedDict):
    id: str
    wave_date: str
    capacity_units: int
    capacity_glass_sqft: float
    allocated_units: int
    allocated_glass_sqft: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ShippingRack(TypedDict):
    id: str
    rack_code: str
    slot_capacity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RackReservation(TypedDict):
    id: str
    rack_id: str
    order_id: str
    load_date: str
    ship_date: str
    assigned_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    order_id: str
    order_line_id: str
    component: str
    coverage_variant: str
    failure_date: str
    description: str
    coverage_pct: int
    remedy: Optional[str]
    remedy_value_cents: Optional[int]
    status: str
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServicePartShipment(TypedDict):
    id: str
    warranty_claim_id: str
    part_sku: str
    quantity: int
    carrier: str
    shipping_charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
