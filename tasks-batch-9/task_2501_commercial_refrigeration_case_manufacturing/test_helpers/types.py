"""Domain types for the Commercial Refrigeration Case Manufacturing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.

Two catalogue resources — refrigerant blends and energy standards — are
immutable reference data and carry ONLY ``id`` and ``created_at`` (PRD §2.4:
"refrigerant blends and energy standards have no `updated_at` field and no
`version` field at all"). Their TypedDicts therefore omit both.
"""

from enum import Enum
from typing import List, Optional, TypedDict

# ─── Role enum (PRD §2.1) ────────────────────────────────────────────────


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DESIGN_ENGINEER = "DesignEngineer"
    TEST_LAB_TECHNICIAN = "TestLabTechnician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SALES_ENGINEER = "SalesEngineer"
    PLANT_SUPERVISOR = "PlantSupervisor"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    INSTALL_CONTRACTOR = "InstallContractor"
    SERVICE_MANAGER = "ServiceManager"


# ─── Enumerated domain vocabularies ─────────────────────────────────────


class TemperatureClass(str, Enum):
    HT = "HT"
    MT = "MT"
    LT = "LT"


class SystemType(str, Enum):
    REMOTE = "REMOTE"
    SELF_CONTAINED = "SELF_CONTAINED"


class SystemTypeScope(str, Enum):
    REMOTE = "REMOTE"
    SELF_CONTAINED = "SELF_CONTAINED"
    ANY = "ANY"


class SafetyClass(str, Enum):
    A1 = "A1"
    A2L = "A2L"
    A3 = "A3"


class DoorType(str, Enum):
    OPEN = "OPEN"
    GLASS_DOOR = "GLASS_DOOR"


class EndCap(str, Enum):
    NONE = "NONE"
    LEFT = "LEFT"
    RIGHT = "RIGHT"
    BOTH = "BOTH"


class MerchandisingOption(str, Enum):
    LED_CANOPY = "LED_CANOPY"
    NIGHT_CURTAIN = "NIGHT_CURTAIN"
    GLASS_DOOR_UPGRADE = "GLASS_DOOR_UPGRADE"
    SHELF_LIGHTING = "SHELF_LIGHTING"
    DIGITAL_PRICE_RAIL = "DIGITAL_PRICE_RAIL"


class ClaimType(str, Enum):
    COMPRESSOR_FAILURE = "COMPRESSOR_FAILURE"
    DOOR_GASKET = "DOOR_GASKET"
    CONTROLLER = "CONTROLLER"
    GLASS_FOG = "GLASS_FOG"


class QaResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SCRAP = "SCRAP"


# ─── Status enums ───────────────────────────────────────────────────────


class CaseModelStatus(str, Enum):
    DRAFT = "DRAFT"
    MODELED = "MODELED"
    SUBMITTED_FOR_TEST = "SUBMITTED_FOR_TEST"
    TESTED_PASS = "TESTED_PASS"
    TESTED_FAIL = "TESTED_FAIL"
    CERTIFIED = "CERTIFIED"
    DECERTIFIED = "DECERTIFIED"


class EnergyTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED_PASS = "COMPLETED_PASS"
    COMPLETED_FAIL = "COMPLETED_FAIL"
    INVALIDATED = "INVALIDATED"


class ComplianceLabelStatus(str, Enum):
    ISSUED = "ISSUED"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class CommercialStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    APPROVED = "APPROVED"
    HOLD_PENDING_RECERT = "HOLD_PENDING_RECERT"


class ProductionStatus(str, Enum):
    NOT_RELEASED = "NOT_RELEASED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETE = "COMPLETE"


class WorkOrderStatus(str, Enum):
    QUEUED = "QUEUED"
    HELD = "HELD"
    SHEET_METAL = "SHEET_METAL"
    FOAM_INJECTION = "FOAM_INJECTION"
    DOOR_ASSEMBLY = "DOOR_ASSEMBLY"
    FINAL_QA = "FINAL_QA"
    REWORK = "REWORK"
    COMPLETE = "COMPLETE"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"


class ShipmentStatus(str, Enum):
    STAGED = "STAGED"
    LOADED = "LOADED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    HANDED_OFF = "HANDED_OFF"
    CANCELLED = "CANCELLED"


class InstallBookingStatus(str, Enum):
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class WarrantyClaimStatus(str, Enum):
    OPEN = "OPEN"
    PARTS_RESERVED = "PARTS_RESERVED"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"


# ─── Entity TypedDicts ──────────────────────────────────────────────────


class Refrigerant(TypedDict):
    """Immutable reference data — id + created_at only (PRD §3.1)."""

    id: str
    created_at: str
    refrigerant_code: str
    trade_name: str
    gwp_100yr: int
    safety_class: str
    max_charge_grams: int
    allowed_system_types: List[str]


class EnergyStandard(TypedDict):
    """Immutable reference data — id + created_at only (PRD §3.1)."""

    id: str
    created_at: str
    standard_code: str
    effective_date: str
    max_gwp: int
    limit_coefficient_a: float
    limit_constant_b: float
    temperature_class: str
    system_type_scope: str


class ChamberRow(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    chamber_code: str
    name: str
    supported_temperature_classes: List[str]
    turnaround_hours: int
    max_tda_sqft: float
    closed_window_start: Optional[str]
    closed_window_end: Optional[str]


class CaseModel(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    model_code: str
    application: str
    temperature_class: str
    system_type: str
    refrigerant_id: str
    predecessor_model_id: Optional[str]
    nominal_length_ft: int
    tda_sqft: float
    charge_grams: int
    line_set_length_ft: int
    door_type: str
    glass_door_count: int
    curtain_layers: int
    discharge_velocity_mps: float
    case_air_temp_c: float
    ambient_dew_point_c: float
    lighting_w_per_ft: float
    fan_w_per_ft: float
    defrost_cycles_per_day: int
    status: str
    design_revision: int
    submitted_by_user_id: Optional[str]
    curtain_factor: Optional[float]
    velocity_factor: Optional[float]
    infiltration_load_w: Optional[float]
    lighting_load_w: Optional[float]
    fan_load_w: Optional[float]
    defrost_load_w: Optional[float]
    anti_sweat_load_w: Optional[float]
    total_design_load_w: Optional[float]
    installed_charge_grams: Optional[int]
    nameplate_co2e_kg: Optional[float]
    installed_co2e_kg: Optional[float]


class EnergyTest(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    case_model_id: str
    test_chamber_id: str
    energy_standard_id: str
    window_start: str
    window_end: str
    test_ambient_c: float
    store_ambient_c: float
    status: str
    pinned_design_revision: int
    pinned_tda_sqft: float
    pinned_defrost_cycles_per_day: int
    limit_daily_kwh: float
    measured_kwh_24h: Optional[float]
    measured_defrost_cycles: Optional[int]
    lab_rated_index: Optional[float]
    field_projected_daily_kwh: Optional[float]
    field_projected_index: Optional[float]
    field_exceedance: Optional[bool]


class ComplianceLabel(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    case_model_id: str
    energy_test_id: str
    label_code: str
    label_status: str
    issued_by_user_id: str
    revocation_reason: Optional[str]
    pinned_design_revision: int
    pinned_lab_rated_index: float
    pinned_standard_code: str


class StorePlan(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    banner_name: str
    store_number: str
    region_code: str
    remodel_window_start: str
    remodel_window_end: str
    credit_limit_cents: int
    commercial_status: str
    production_status: str
    line_count: int
    unit_count: int
    held_line_count: int
    units_completed_count: int
    units_shipped_count: int
    warranty_reserve_accrual_cents: int
    warranty_reserve_incurred_cents: int
    priced_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    subtotal_cents: Optional[int]
    volume_discount_bps: Optional[int]
    volume_discount_cents: Optional[int]
    net_cents: Optional[int]
    freight_cents: Optional[int]
    install_allowance_cents: Optional[int]
    total_cents: Optional[int]


class StorePlanLine(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_plan_id: str
    case_model_id: str
    length_ft: int
    quantity: int
    end_cap: str
    merchandising_options: List[str]
    unit_price_cents: Optional[int]
    extended_price_cents: Optional[int]
    compliance_hold: bool


class WorkOrder(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_plan_id: str
    store_plan_line_id: str
    case_model_id: str
    shipment_id: Optional[str]
    unit_sequence: int
    unit_price_cents: int
    serial_number: str
    rework_count: int
    warranty_start_date: Optional[str]
    status: str


class Shipment(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    store_plan_id: str
    ship_date: str
    delivery_date: str
    carrier_code: str
    status: str
    unit_count: int
    linear_feet: int
    handoff_at: Optional[str]
    received_by_name: Optional[str]


class InstallCrew(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    crew_code: str
    contractor_name: str
    service_region_codes: List[str]
    daily_case_capacity: int
    committed_case_days: int


class InstallBooking(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    shipment_id: str
    install_crew_id: str
    start_date: str
    end_date: str
    cases_committed: int
    day_count: int
    status: str


class PartInventory(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    part_number: str
    description: str
    case_model_id: str
    region_code: str
    on_hand_qty: int
    unit_cost_cents: int
    min_stock_qty: int
    reserved_qty: int
    available_qty: int
    below_min: bool


class WarrantyClaim(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int
    work_order_id: str
    part_inventory_id: str
    install_crew_id: str
    claim_type: str
    reported_date: str
    requested_qty: int
    estimated_cost_cents: int
    status: str
    warranty_term_months: int
    in_warranty: bool
    parts_cost_cents: Optional[int]
    labor_cost_cents: Optional[int]
    total_cost_cents: Optional[int]
    denial_reason: Optional[str]
