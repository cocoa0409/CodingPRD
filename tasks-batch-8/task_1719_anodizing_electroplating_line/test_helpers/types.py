"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PriorityTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"


class RoutingMode(str, Enum):
    RACK = "RACK"
    BARREL = "BARREL"


class ProcessType(str, Enum):
    ANODIZE = "ANODIZE"
    PLATE = "PLATE"


class ChemistryFamily(str, Enum):
    SULFURIC = "SULFURIC"
    CHROMIC = "CHROMIC"
    NICKEL = "NICKEL"
    ZINC = "ZINC"
    COPPER = "COPPER"
    CYANIDE = "CYANIDE"


class Compatibility(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    CONDITIONAL = "CONDITIONAL"
    INCOMPATIBLE = "INCOMPATIBLE"


class BathStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"
    EXHAUSTED = "EXHAUSTED"
    DUMPED = "DUMPED"
    DECOMMISSIONED = "DECOMMISSIONED"


class QuarantineCause(str, Enum):
    MANUAL = "MANUAL"
    DISCHARGE_EXCEEDANCE = "DISCHARGE_EXCEEDANCE"


class WorkOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    READY_FOR_ROUTING = "READY_FOR_ROUTING"
    ROUTED = "ROUTED"
    ROUTE_HELD = "ROUTE_HELD"
    IN_PROCESS = "IN_PROCESS"
    AWAITING_INSPECTION = "AWAITING_INSPECTION"
    AWAITING_LOT_TEST = "AWAITING_LOT_TEST"
    REJECTED = "REJECTED"
    STRIPPING = "STRIPPING"
    COMPLETE = "COMPLETE"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"
    CANCELLED = "CANCELLED"


class LoadRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class DefectType(str, Enum):
    NONE = "NONE"
    BURN = "BURN"
    STAIN = "STAIN"
    PITTING = "PITTING"
    ADHESION = "ADHESION"
    UNDERTHICKNESS = "UNDERTHICKNESS"


class Disposition(str, Enum):
    PASS = "PASS"
    REWORKABLE_REJECT = "REWORKABLE_REJECT"
    SCRAP_REJECT = "SCRAP_REJECT"


class LotResult(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class PermitStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXCEEDED = "EXCEEDED"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"


class SourceType(str, Enum):
    BATH_DUMP = "BATH_DUMP"
    SLUDGE_PRESS = "SLUDGE_PRESS"
    RINSE_CONCENTRATE = "RINSE_CONCENTRATE"


class UserRole(str, Enum):
    CUSTOMER = "Customer"
    LINE_OPERATOR = "LineOperator"
    LAB_CHEMIST = "LabChemist"
    QC_INSPECTOR = "QCInspector"
    EHS_OFFICER = "EHSOfficer"
    SHOP_MANAGER = "ShopManager"


# --- Entity TypedDicts (common_fields: true -> id + created_at + updated_at + version) ---


class Customer(TypedDict, total=False):
    id: str
    company_name: str
    priority_tier: str
    credit_hold: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Fixture(TypedDict, total=False):
    id: str
    fixture_code: str
    routing_mode: str
    capacity_dm2: float
    purchase_cost_cents: int
    rated_uses: int
    amortization_cents_per_use: int
    created_at: str
    updated_at: str
    version: int


class AlloyCompatibilityRule(TypedDict, total=False):
    id: str
    alloy_code: str
    process_type: str
    chemistry_family: str
    compatibility: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlatingBath(TypedDict, total=False):
    id: str
    bath_code: str
    process_type: str
    chemistry_family: str
    routing_modes_supported: List[str]
    volume_liters: float
    target_concentration_g_l: float
    low_concentration_g_l: float
    high_concentration_g_l: float
    amp_hour_capacity: float
    current_concentration_g_l: Optional[float]
    amp_hour_used: float
    amp_hour_reserved: float
    active_load_run_id: Optional[str]
    dose_verification_pending: bool
    quarantine_cause: Optional[str]
    status: str
    nameplate_remaining_ah: float
    effective_remaining_ah: int
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    customer_id: str
    part_number: str
    alloy_code: str
    process_type: str
    routing_mode: str
    part_count: int
    surface_area_dm2_per_part: float
    surface_area_total_dm2: float
    thickness_spec_min_um: float
    thickness_spec_max_um: float
    requires_masking: bool
    masking_minutes_actual: Optional[int]
    requires_salt_spray: bool
    predip_completed: bool
    bath_id: Optional[str]
    fixture_id: Optional[str]
    routed_chemistry_family: Optional[str]
    rework_count: int
    pending_strip: bool
    last_defect_type: Optional[str]
    provisional_quote_cents: int
    final_invoice_cents: Optional[int]
    completed_load_count: int
    cancellation_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class LoadRun(TypedDict, total=False):
    id: str
    work_order_id: str
    bath_id: str
    fixture_id: Optional[str]
    duration_minutes: int
    current_density_a_dm2: float
    surface_area_dm2: float
    estimated_amp_hours: float
    amp_hours_consumed: Optional[float]
    started_at: str
    ended_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SaltSprayLot(TypedDict, total=False):
    id: str
    work_order_id: str
    sample_count: int
    hours_required: int
    allowed_failures: int
    panels_failed: Optional[int]
    hours_run: int
    result: str
    created_at: str
    updated_at: str
    version: int


class DischargePermit(TypedDict, total=False):
    id: str
    outfall_code: str
    effective_from: str
    effective_to: str
    limits: List[Dict[str, Any]]
    current_month: Optional[str]
    cumulative_mass_g: Dict[str, float]
    last_sampled_at: Optional[str]
    exceedance_active: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WasteManifest(TypedDict, total=False):
    id: str
    generator_epa_id: str
    transporter_name: Optional[str]
    created_by_user_id: str
    finalized_by_user_id: Optional[str]
    total_mass_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ManifestLineItem(TypedDict, total=False):
    id: str
    manifest_id: str
    waste_code: str
    source_type: str
    description: str
    volume_liters: float
    mass_kg: float
    origin_bath_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Append-only event records (common_fields: false -> ONLY id + created_at) ---


class BathTitration(TypedDict, total=False):
    id: str
    bath_id: str
    titrant_volume_ml: float
    titrant_normality: float
    sample_volume_ml: float
    measured_concentration_g_l: float
    created_at: str


class DoseEvent(TypedDict, total=False):
    id: str
    bath_id: str
    chemical_code: str
    quantity_g: float
    resulting_concentration_g_l: float
    created_at: str


class InspectionReport(TypedDict, total=False):
    id: str
    work_order_id: str
    load_run_id: str
    thickness_readings_um: List[float]
    defect_type: str
    thickness_min_um: float
    thickness_max_um: float
    thickness_ok: bool
    disposition: str
    created_at: str


class WasteSample(TypedDict, total=False):
    id: str
    permit_id: str
    sampled_at: str
    flow_liters: float
    readings: List[Dict[str, Any]]
    masses_g: Dict[str, float]
    is_exceedance: bool
    created_at: str
