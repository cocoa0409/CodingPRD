"""Domain types for the Residential HVAC Equipment Plant API.

Status enums, value enums, entity TypedDicts, and the role enum. Field names
and enum spellings are taken verbatim from the PRD.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1 — eleven roles, spelled exactly)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    DESIGN_ENGINEER = "DesignEngineer"
    RELIABILITY_ENGINEER = "ReliabilityEngineer"
    CERTIFICATION_ENGINEER = "CertificationEngineer"
    REGULATORY_AUDITOR = "RegulatoryAuditor"
    SUPPLY_PLANNER = "SupplyPlanner"
    PRODUCTION_PLANNER = "ProductionPlanner"
    PRODUCTION_TECHNICIAN = "ProductionTechnician"
    QUALITY_TECHNICIAN = "QualityTechnician"
    DISTRIBUTOR_REP = "DistributorRep"
    WARRANTY_ANALYST = "WarrantyAnalyst"


# ---------------------------------------------------------------------------
# Status enums (one per lifecycle described in PRD §3)
# ---------------------------------------------------------------------------


class RefrigerantProgramStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SELL_THROUGH = "SELL_THROUGH"
    EXPIRED = "EXPIRED"


class RegionalStandardStatus(str, Enum):
    ACTIVE = "ACTIVE"


class ProductPlatformStatus(str, Enum):
    DRAFT = "DRAFT"
    ENG_REVIEW = "ENG_REVIEW"
    RELEASED = "RELEASED"
    RESTRICTED = "RESTRICTED"
    RETIRED = "RETIRED"


class CertificationRecordStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"


class ComponentSupplyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    DERATED = "DERATED"
    CLOSED = "CLOSED"


class AllocationLineStatus(str, Enum):
    RESERVED = "RESERVED"
    COMMITTED = "COMMITTED"
    REVOKED = "REVOKED"
    RELEASED = "RELEASED"


class OrderAllocationStatus(str, Enum):
    UNALLOCATED = "UNALLOCATED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    FULLY_ALLOCATED = "FULLY_ALLOCATED"


class OrderFulfillmentStatus(str, Enum):
    PENDING = "PENDING"
    STAGED = "STAGED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class WarehouseReservationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class TestCellStatus(str, Enum):
    ACTIVE = "ACTIVE"


class BuildOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    COIL_FAB = "COIL_FAB"
    BRAZED = "BRAZED"
    REWORK = "REWORK"
    LEAK_PASSED = "LEAK_PASSED"
    CHARGED = "CHARGED"
    RUN_PASSED = "RUN_PASSED"
    RELEASED_TO_STOCK = "RELEASED_TO_STOCK"
    SCRAPPED = "SCRAPPED"
    CANCELLED = "CANCELLED"
    HOLD_REGULATORY = "HOLD_REGULATORY"


class WarrantyClaimStatus(str, Enum):
    OPEN = "OPEN"
    LINKED_TO_CAPA = "LINKED_TO_CAPA"
    CLOSED = "CLOSED"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_EFFECTIVE = "CLOSED_EFFECTIVE"
    CLOSED_INEFFECTIVE = "CLOSED_INEFFECTIVE"


# ---------------------------------------------------------------------------
# Value enums
# ---------------------------------------------------------------------------


class FlammabilityClass(str, Enum):
    A1 = "A1"
    A2L = "A2L"


class EfficiencyTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    PREMIUM = "PREMIUM"


class WarrantyPosture(str, Enum):
    OK = "OK"
    CAPA_REQUIRED = "CAPA_REQUIRED"
    DESIGN_CHANGE_REQUIRED = "DESIGN_CHANGE_REQUIRED"


class ComponentType(str, Enum):
    COMPRESSOR = "COMPRESSOR"
    CONTROL_BOARD = "CONTROL_BOARD"


class AllocationPolicy(str, Enum):
    PRIORITY_WATERFALL = "PRIORITY_WATERFALL"
    DEMAND_PRORATA = "DEMAND_PRORATA"


class LeakTestMethod(str, Enum):
    HELIUM_MASS_SPEC = "HELIUM_MASS_SPEC"
    PRESSURE_DECAY = "PRESSURE_DECAY"


class TestVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FailureCode(str, Enum):
    COMPRESSOR_FAILURE = "COMPRESSOR_FAILURE"
    CONTROL_BOARD_FAULT = "CONTROL_BOARD_FAULT"
    COIL_LEAK = "COIL_LEAK"
    CHARGE_LOSS = "CHARGE_LOSS"
    FAN_MOTOR = "FAN_MOTOR"


class CertificationDecision(str, Enum):
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class CorrectiveActionResolution(str, Enum):
    EFFECTIVE = "EFFECTIVE"
    INEFFECTIVE = "INEFFECTIVE"


class CarryingCostBasis(str, Enum):
    PER_RESERVATION = "PER_RESERVATION"
    POOLED = "POOLED"


class WarrantyAnalysisBasis(str, Enum):
    BUILT_BASIS = "BUILT_BASIS"
    SHIPPED_BASIS = "SHIPPED_BASIS"


class BuildOrderHoldReason(str, Enum):
    REFRIGERANT_SELL_THROUGH = "REFRIGERANT_SELL_THROUGH"


class BuildOrderClosedReason(str, Enum):
    REWORK_LIMIT_EXCEEDED = "REWORK_LIMIT_EXCEEDED"
    PLATFORM_RETIRED = "PLATFORM_RETIRED"


class ReservationReleaseReason(str, Enum):
    BUILD_ON_REGULATORY_HOLD = "BUILD_ON_REGULATORY_HOLD"
    BUILD_CANCELLED = "BUILD_CANCELLED"
    BUILD_SCRAPPED = "BUILD_SCRAPPED"


class AllocationLineClosedReason(str, Enum):
    ORDER_CANCELLED = "ORDER_CANCELLED"
    PLATFORM_RETIRED = "PLATFORM_RETIRED"
    SUPPLY_CLOSED = "SUPPLY_CLOSED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
#
# Most rows expose id, created_at, updated_at, and version (PRD §2.5). Leak
# tests and run tests are append-only and hold ONLY id and created_at
# alongside their own fields — their TypedDicts deliberately omit updated_at
# and version.
# ---------------------------------------------------------------------------


class RefrigerantProgram(TypedDict):
    id: str
    refrigerant_code: str
    gwp: int
    flammability_class: str
    manufacture_cutoff_utc: str
    sell_through_deadline_utc: str
    status: str
    sell_through_entered_at: Optional[str]
    expired_at: Optional[str]
    affected_platform_count: int
    created_at: str
    updated_at: str
    version: int


class RegionalStandard(TypedDict):
    id: str
    region_code: str
    min_seer2_standard: float
    min_seer2_high: float
    min_seer2_premium: float
    prohibits_flammable_refrigerant: bool
    effective_from_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductPlatform(TypedDict):
    id: str
    model_code: str
    efficiency_tier: str
    refrigerant_program_id: str
    supersedes_platform_id: Optional[str]
    rated_capacity_btuh: int
    rated_eer: float
    rated_seer2: float
    compressor_part_number: str
    control_board_part_number: str
    max_charge_grams: Optional[int]
    status: str
    revision_round: int
    submitted_by_user_id: Optional[str]
    released_at: Optional[str]
    last_revision_notes: Optional[str]
    blocked_region_codes: List[str]
    salable_region_count: int
    warranty_posture: str
    rolling_claim_rate_pct: float
    units_built_released: int
    units_shipped_total: int
    created_at: str
    updated_at: str
    version: int


class CertificationRecord(TypedDict):
    id: str
    platform_id: str
    region_code: str
    rated_seer2_submitted: float
    status: str
    governing_standard_id: Optional[str]
    submitted_by_user_id: Optional[str]
    submitted_at: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    rejection_reason: Optional[str]
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComponentSupply(TypedDict):
    id: str
    component_type: str
    part_number: str
    supplier_lot_code: str
    supply_month: str
    total_allocatable_units: int
    allocation_policy: str
    status: str
    derate_pct: int
    effective_allocatable_units: int
    reserved_units: int
    committed_units: int
    available_units: int
    created_at: str
    updated_at: str
    version: int


class AllocationLine(TypedDict):
    id: str
    distributor_order_id: str
    component_supply_id: str
    component_type: str
    units: int
    status: str
    closed_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DistributorOrder(TypedDict):
    id: str
    distributor_code: str
    platform_id: str
    region_code: str
    requested_units: int
    priority_score: int
    requested_delivery_month: str
    allocation_status: str
    fulfillment_status: str
    allocated_units: int
    shipped_units: int
    staged_at: Optional[str]
    shipped_at: Optional[str]
    cancelled_at: Optional[str]
    created_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict):
    id: str
    name: str
    pallet_capacity: int
    pallets_reserved_current: int
    created_at: str
    updated_at: str
    version: int


class WarehouseReservation(TypedDict):
    id: str
    warehouse_id: str
    build_order_id: str
    start_date: str
    end_date: str
    pallet_units: int
    status: str
    released_at: Optional[str]
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestCell(TypedDict):
    id: str
    cell_code: str
    cooldown_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildOrder(TypedDict):
    id: str
    platform_id: str
    quantity_units: int
    scheduled_start_utc: str
    is_preseason: bool
    status: str
    rework_count: int
    charge_grams: int
    hold_reason: Optional[str]
    closed_reason: Optional[str]
    released_to_stock_at: Optional[str]
    latest_leak_verdict: Optional[str]
    latest_run_verdict: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LeakTest(TypedDict):
    """Append-only: holds only id and created_at alongside its own fields."""

    id: str
    build_order_id: str
    method: str
    measured_leak_rate_g_per_year: Optional[float]
    decay_kpa: Optional[float]
    hold_minutes: Optional[int]
    applied_limit: float
    verdict: str
    performed_by_user_id: str
    performed_at: str
    created_at: str


class RunTest(TypedDict):
    """Append-only: holds only id and created_at alongside its own fields."""

    id: str
    build_order_id: str
    test_cell_id: str
    window_start_utc: str
    window_end_utc: str
    measured_capacity_btuh: int
    measured_power_w: int
    measured_ambient_c: float
    corrected_capacity_btuh: int
    capacity_ratio: float
    efficiency_ratio: float
    applied_capacity_tolerance: float
    applied_efficiency_tolerance: float
    verdict: str
    performed_by_user_id: str
    performed_at: str
    created_at: str


class WarrantyClaim(TypedDict):
    id: str
    platform_id: str
    build_order_id: Optional[str]
    failure_code: str
    claim_cost_cents: int
    component_type: Optional[str]
    supplier_lot_code: Optional[str]
    status: str
    filed_by_user_id: str
    filed_at: str
    created_at: str
    updated_at: str
    version: int


class SupplierCorrectiveAction(TypedDict):
    id: str
    component_supply_id: str
    warranty_claim_id: str
    supplier_lot_code: str
    component_type: str
    trigger_claim_rate_pct: float
    derate_pct: int
    cited_claim_count: int
    status: str
    resolution: Optional[str]
    effectiveness_note: Optional[str]
    closed_by_user_id: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
