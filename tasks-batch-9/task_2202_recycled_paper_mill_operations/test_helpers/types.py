"""Domain types for the Recycled Paper Mill Operations API."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    MILL_PLANNER = "MillPlanner"
    FIBER_BUYER = "FiberBuyer"
    QUALITY_LAB = "QualityLab"
    MACHINE_OPERATOR = "MachineOperator"
    ENVIRONMENTAL_OFFICER = "EnvironmentalOfficer"
    ENERGY_MANAGER = "EnergyManager"
    SUPPLIER = "Supplier"
    CUSTOMER = "Customer"


class CustomerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SupplierQualificationStatus(str, Enum):
    QUALIFIED = "QUALIFIED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class PurchaseOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PRICED = "PRICED"
    CONFIRMED = "CONFIRMED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ReceiptStatus(str, Enum):
    SAMPLED = "SAMPLED"
    ACCEPTED = "ACCEPTED"
    DOWNGRADED = "DOWNGRADED"
    REJECTED = "REJECTED"


class InventoryLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class PulpBatchStatus(str, Enum):
    QUEUED = "QUEUED"
    PULPING = "PULPING"
    SCREENED = "SCREENED"
    CLEANED = "CLEANED"
    DEINKING = "DEINKING"
    DEINK_HOLD = "DEINK_HOLD"
    APPROVED = "APPROVED"
    DIVERTED = "DIVERTED"
    CANCELLED = "CANCELLED"


class PulperLine(str, Enum):
    OCC_LINE = "OCC_LINE"
    DIP_LINE = "DIP_LINE"


class MachineStatus(str, Enum):
    RUNNABLE = "RUNNABLE"
    DOWN = "DOWN"


class RunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class QualityStatus(str, Enum):
    PENDING = "PENDING"
    PROVISIONAL = "PROVISIONAL"
    HELD = "HELD"
    REWORK = "REWORK"
    CERTIFIED = "CERTIFIED"
    CONDEMNED = "CONDEMNED"


class GradeChangeStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class RollSetStatus(str, Enum):
    WOUND = "WOUND"
    WRAPPED = "WRAPPED"
    QUARANTINED = "QUARANTINED"
    REWOUND = "REWOUND"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    SCRAPPED = "SCRAPPED"


class OrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    ALLOCATED = "ALLOCATED"
    SHIPPED = "SHIPPED"
    SHORT_CLOSED = "SHORT_CLOSED"
    CANCELLED = "CANCELLED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    WATCH = "WATCH"
    EXCEEDANCE = "EXCEEDANCE"


class ManifestStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    VOIDED = "VOIDED"


class ManifestDestination(str, Enum):
    LANDFILL = "LANDFILL"
    LAND_APPLICATION = "LAND_APPLICATION"
    FUEL = "FUEL"


class SolidsSourceKind(str, Enum):
    PULP_REJECT = "PULP_REJECT"
    DEINK_SLUDGE = "DEINK_SLUDGE"
    MACHINE_BROKE = "MACHINE_BROKE"
    TRANSITION_WASTE = "TRANSITION_WASTE"


class SolidsDisposition(str, Enum):
    PENDING = "PENDING"
    MANIFESTED = "MANIFESTED"
    REPULPED = "REPULPED"


class SteamStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    CURTAILED = "CURTAILED"
    RELEASED = "RELEASED"


class WrapSpec(str, Enum):
    KRAFT_ONLY = "KRAFT_ONLY"
    POLY_COATED = "POLY_COATED"
    STRETCH_HOOD = "STRETCH_HOOD"


# --- entities carrying the full id/created_at/updated_at/version quartet ---

class Customer(TypedDict):
    id: str
    name: str
    allocation_priority_tier: str
    max_roll_diameter_mm: int
    max_roll_width_mm: int
    wrap_spec: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    name: str
    freight_per_ton: float
    contamination_strike_count: int
    qualification_status: str
    probation_entered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FiberPurchaseOrder(TypedDict):
    id: str
    supplier_id: str
    fiber_grade_code: str
    contracted_tons: float
    index_basis: str
    priced_for_month: str
    negotiated_delta_per_ton: float
    quoted_unit_price_per_ton: Optional[float]
    fuel_surcharge_per_ton: Optional[float]
    extended_contract_value: Optional[float]
    index_quote_month_used: Optional[str]
    pricing_revision_count: int
    received_net_tons: float
    status: str
    created_at: str
    updated_at: str
    version: int


# --- entities carrying only id + created_at (immutable / append-only) ---

class FiberGrade(TypedDict):
    id: str
    grade_code: str
    index_symbol: str
    max_contamination_pct: float
    max_moisture_pct: float
    nominal_yield_pct: float
    deink_required: bool
    downgrade_target_grade_code: Optional[str]
    rank_order: int
    created_at: str


class MarketIndexQuote(TypedDict):
    id: str
    index_symbol: str
    effective_month: str
    published_price_per_ton: float
    superseded: bool
    created_at: str


class PaperGradeSpec(TypedDict):
    id: str
    product_code: str
    family: str
    basis_weight_gsm: float
    target_moisture_pct: float
    moisture_tolerance_pct: float
    min_sct_kn_m: float
    min_brightness_iso: Optional[float]
    requires_deink_pulp: bool
    rank_order: int
    created_at: str


class RejectStream(TypedDict):
    id: str
    source_kind: str
    source_ref_id: str
    dry_solids_tons: float
    disposition: str
    manifest_id: Optional[str]
    reversal_of_id: Optional[str]
    created_at: str


class FiberReceipt(TypedDict):
    id: str
    purchase_order_id: str
    supplier_id: str
    truck_reference: str
    sublots: List[dict]
    declared_grade_code: str
    net_tons: float
    weighted_contamination_pct: float
    weighted_moisture_pct: float
    moisture_deduction_tons: float
    accepted_grade_code: Optional[str]
    sampled_by_user_id: str
    dispositioned_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FiberInventoryLot(TypedDict):
    id: str
    receipt_id: str
    grade_code: str
    contamination_pct: float
    tons_received: float
    tons_consumed: float
    tons_available: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PulpBatch(TypedDict):
    id: str
    pulper_line: str
    target_product_code: str
    furnish_lines: List[dict]
    charged_tons: Optional[float]
    blend_contamination_pct: Optional[float]
    provisional_accepted_tons: Optional[float]
    measured_reject_tons: Optional[float]
    final_accepted_tons: Optional[float]
    yield_variance_tons: Optional[float]
    consumed_tons: float
    available_tons: float
    caustic_kg: float
    peroxide_kg: float
    surfactant_kg: float
    deink_pass_count: int
    brightness_iso: Optional[float]
    cumulative_chemical_cost: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PaperMachine(TypedDict):
    id: str
    name: str
    wire_width_mm: int
    max_tons_per_hour: float
    changeover_buffer_minutes: int
    steam_tph_per_ton: float
    current_product_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerOrder(TypedDict):
    id: str
    customer_id: str
    product_code: str
    ordered_tons: float
    requested_ship_date: str
    roll_width_mm: int
    roll_diameter_mm: int
    wrap_spec: str
    allocated_tons: float
    shipped_tons: float
    shortfall_tons: float
    scheduled_run_id: Optional[str]
    deschedule_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    machine_id: str
    product_code: str
    pulp_batch_id: str
    window_start: str
    window_end: str
    pulp_draw_tons: float
    produced_tons: float
    broke_tons: float
    reel_readings: Optional[List[dict]]
    provisional_quality_index: Optional[float]
    certified_quality_index: Optional[float]
    off_spec_reel_count: int
    started_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    run_status: str
    quality_status: str
    created_at: str
    updated_at: str
    version: int


class GradeChange(TypedDict):
    id: str
    machine_id: str
    from_run_id: str
    to_run_id: str
    from_product_code: str
    to_product_code: str
    transition_waste_tons: float
    transition_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RollSet(TypedDict):
    id: str
    production_run_id: str
    slit_width_mm: int
    diameter_mm: int
    roll_count: int
    net_tons: float
    wrap_spec: Optional[str]
    allocated_order_id: Optional[str]
    rewind_count: int
    quarantine_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class EffluentPermit(TypedDict):
    id: str
    permit_number: str
    bod_limit_kg_per_day: float
    tss_limit_kg_per_day: float
    flow_limit_m3_per_day: float
    rolling_window_days: int
    rolling_bod_kg_per_day: float
    rolling_tss_kg_per_day: float
    exceedance_day_count: int
    compliance_posture: str
    posture_changed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EffluentReading(TypedDict):
    id: str
    permit_id: str
    reading_date: str
    flow_m3: float
    bod_kg: float
    tss_kg: float
    logged_by_user_id: str
    voided: bool
    created_at: str
    updated_at: str
    version: int


class SludgeManifest(TypedDict):
    id: str
    manifest_number: str
    destination: str
    reject_stream_ids: List[str]
    total_dry_solids_tons: float
    prepared_by_user_id: str
    signed_by_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SteamAllocation(TypedDict):
    id: str
    consumer_kind: str
    consumer_ref_id: Optional[str]
    window_start: str
    window_end: str
    demand_tph: float
    priority_rank: int
    granted_tph: float
    curtailed_tph: float
    cogen_credit_usd: float
    status: str
    created_at: str
    updated_at: str
    version: int
