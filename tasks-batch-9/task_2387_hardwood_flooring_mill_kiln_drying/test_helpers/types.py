"""Domain types for the Hardwood Flooring Mill & Kiln Drying API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    MILL_ADMIN = "MillAdmin"
    PROCUREMENT_CLERK = "ProcurementClerk"
    KILN_OPERATOR = "KilnOperator"
    MILL_SUPERVISOR = "MillSupervisor"
    GRADE_INSPECTOR = "GradeInspector"
    PREFINISH_SCHEDULER = "PrefinishScheduler"
    BYPRODUCT_BROKER = "ByproductBroker"
    WARRANTY_ADJUDICATOR = "WarrantyAdjudicator"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Enumerated value sets
# ---------------------------------------------------------------------------


class DensityClass(str, Enum):
    DENSE = "DENSE"
    MEDIUM = "MEDIUM"
    SOFT = "SOFT"


class ReceiptGrade(str, Enum):
    FAS = "FAS"
    SELECT = "SELECT"
    NO1_COMMON = "NO1_COMMON"
    NO2_COMMON = "NO2_COMMON"


class ConstructionType(str, Enum):
    SOLID = "SOLID"
    ENGINEERED = "ENGINEERED"


class CoreMaterial(str, Enum):
    BIRCH_PLY = "BIRCH_PLY"
    HDF = "HDF"
    EUCALYPTUS_PLY = "EUCALYPTUS_PLY"


class InspectorRuleset(str, Enum):
    NHLA = "NHLA"
    MILL_CHARACTER = "MILL_CHARACTER"


class GradeClass(str, Enum):
    CLEAR = "CLEAR"
    SELECT = "SELECT"
    NO1_COMMON = "NO1_COMMON"
    NO2_COMMON = "NO2_COMMON"
    CHARACTER = "CHARACTER"
    CABIN = "CABIN"


class ByproductType(str, Enum):
    SAWDUST = "SAWDUST"
    SHAVINGS = "SHAVINGS"
    SHORTS = "SHORTS"


class ClaimType(str, Enum):
    CUPPING = "CUPPING"
    GAPPING = "GAPPING"


class AdjudicationDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"


# ---------------------------------------------------------------------------
# Status enums (PRD §3)
# ---------------------------------------------------------------------------


class GreenReceiptStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    ALLOCATED = "ALLOCATED"
    CONSUMED = "CONSUMED"
    REJECTED = "REJECTED"


class KilnChamberStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    MAINTENANCE = "MAINTENANCE"


class KilnChargeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPLACED = "DISPLACED"
    LOADED = "LOADED"
    DRYING = "DRYING"
    CONDITIONING = "CONDITIONING"
    REDRY = "REDRY"
    RELEASED = "RELEASED"
    CLOSED = "CLOSED"


class FlooringLotStatus(str, Enum):
    PLANNED = "PLANNED"
    MILLED = "MILLED"
    GRADED = "GRADED"
    QUARANTINED = "QUARANTINED"
    VOIDED = "VOIDED"


class GradeRunStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    SUPERSEDED = "SUPERSEDED"


class PrefinishRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class ProductLinePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AdjudicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVERSED = "REVERSED"


class RemediationStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------


class SpeciesProfile(TypedDict):
    id: str
    species_code: str
    common_name: str
    density_class: str
    tangential_shrinkage_coefficient: float
    target_moisture_pct: float
    max_moisture_gradient_pp: float
    green_to_dry_shrink_pct: float
    created_at: str
    updated_at: str
    version: int


class DryingSchedule(TypedDict):
    id: str
    species_profile_id: str
    schedule_code: str
    thickness_in: float
    initial_moisture_pct: float
    final_moisture_pct: float
    conditioning_hours: float
    stress_relief_hours: float
    planned_dry_hours: float
    created_at: str
    updated_at: str
    version: int


class KilnChamber(TypedDict):
    id: str
    chamber_code: str
    capacity_board_feet: int
    status: str
    maintenance_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GreenReceipt(TypedDict):
    id: str
    species_profile_id: str
    supplier_name: str
    received_board_feet: int
    receipt_grade: str
    moisture_pct_at_receipt: float
    accepted_board_feet: int
    status: str
    kiln_charge_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class KilnCharge(TypedDict):
    id: str
    drying_schedule_id: str
    kiln_chamber_id: str
    planned_start_utc: str
    planned_dry_hours: float
    planned_end_utc: str
    blocked_until_utc: str
    status: str
    charged_green_bf: int
    weighted_initial_moisture_pct: Optional[float]
    shell_moisture_pct: Optional[float]
    core_moisture_pct: Optional[float]
    moisture_gradient_pp: Optional[float]
    average_moisture_pct: Optional[float]
    redry_count: int
    dry_bf_out: Optional[float]
    remaining_dry_bf: Optional[float]
    displaced_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductLine(TypedDict):
    id: str
    line_code: str
    species_profile_id: str
    construction_type: str
    nominal_width_in: float
    nominal_thickness_in: float
    material_value_cents_per_sf: int
    warranty_funded_total_cents: int
    warranty_balance_cents: int
    warranty_committed_cents: int
    freeze_override: bool
    posture: str
    created_at: str
    updated_at: str
    version: int


class CoreStock(TypedDict):
    id: str
    product_line_id: str
    core_material: str
    lot_reference: str
    available_square_feet: float
    reserved_square_feet: float
    created_at: str
    updated_at: str
    version: int


class PrefinishLine(TypedDict):
    id: str
    line_code: str
    daily_capacity_linear_feet: int
    coating_passes: int
    created_at: str
    updated_at: str
    version: int


class FlooringLot(TypedDict):
    id: str
    product_line_id: str
    kiln_charge_id: str
    core_stock_id: Optional[str]
    input_dry_bf: float
    construction_type: str
    nominal_width_in: float
    reserved_core_sf: Optional[float]
    dimensional_growth_allowance_in: float
    planned_finished_width_in: float
    actual_milled_width_in: Optional[float]
    net_flooring_bf: Optional[float]
    shorts_bf: Optional[float]
    sawdust_tons: Optional[float]
    shavings_tons: Optional[float]
    residue_bf: Optional[float]
    waste_bf: Optional[float]
    provisional_yield_pct: Optional[float]
    final_yield_pct: Optional[float]
    final_grade_run_id: Optional[str]
    quarantine_reason: Optional[str]
    void_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class GradeRun(TypedDict):
    id: str
    flooring_lot_id: str
    inspector_ruleset: str
    status: str
    tally_board_feet: Optional[float]
    credited_board_feet: Optional[float]
    tally_value_cents: Optional[int]
    superseded_by_run_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GradeBundle(TypedDict):
    """An immutable tally line: it carries only ``id`` and ``created_at``.

    Per the PRD it has no ``updated_at`` field and no ``version`` field at all.
    """

    id: str
    grade_run_id: str
    grade_class: str
    bundle_board_feet: float
    average_length_in: float
    length_factor: float
    credit_factor: float
    tally_value_cents: int
    created_at: str


class PrefinishRun(TypedDict):
    id: str
    prefinish_line_id: str
    flooring_lot_id: str
    product_line_id: str
    window_start_utc: str
    window_end_utc: str
    scheduled_linear_feet: int
    sanding_grit_sequence: str
    stain_code: Optional[str]
    coating_liters: float
    status: str
    hold_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ByproductBatch(TypedDict):
    id: str
    flooring_lot_id: str
    byproduct_type: str
    available_tons: float
    sold_tons: float
    created_at: str
    updated_at: str
    version: int


class ByproductSale(TypedDict):
    id: str
    byproduct_batch_id: str
    buyer_name: str
    quantity_tons: float
    unit_price_cents_per_ton: int
    haul_distance_miles: float
    gross_cents: int
    discount_cents: int
    haul_cents: int
    net_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    product_line_id: str
    flooring_lot_id: Optional[str]
    claim_type: str
    affected_square_feet: float
    installation_date: str
    subfloor_moisture_pct_at_install: float
    ambient_rh_pct_at_install: float
    estimated_liability_cents: int
    adjudication_status: str
    remediation_status: str
    submitted_by_user_id: str
    adjudicated_by_user_id: Optional[str]
    adjudicated_affected_sf: Optional[float]
    adjudicated_subfloor_moisture_pct: Optional[float]
    adjudicated_ambient_rh_pct: Optional[float]
    installer_share_pct: Optional[float]
    mill_share_pct: Optional[float]
    service_months: Optional[int]
    depreciation_pct: Optional[float]
    adjudicated_liability_cents: Optional[int]
    info_request_note: Optional[str]
    denial_reason: Optional[str]
    reversal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class YieldSummary(TypedDict):
    flooring_lot_id: str
    input_dry_bf: float
    net_flooring_bf: Optional[float]
    residue_bf: Optional[float]
    waste_bf: Optional[float]
    provisional_yield_pct: Optional[float]
    final_yield_pct: Optional[float]
    yield_delta_pp: Optional[float]
    yield_floor_pct: float


__all__ = [
    "UserRole",
    "DensityClass",
    "ReceiptGrade",
    "ConstructionType",
    "CoreMaterial",
    "InspectorRuleset",
    "GradeClass",
    "ByproductType",
    "ClaimType",
    "AdjudicationDecision",
    "GreenReceiptStatus",
    "KilnChamberStatus",
    "KilnChargeStatus",
    "FlooringLotStatus",
    "GradeRunStatus",
    "PrefinishRunStatus",
    "ProductLinePosture",
    "AdjudicationStatus",
    "RemediationStatus",
    "SpeciesProfile",
    "DryingSchedule",
    "KilnChamber",
    "GreenReceipt",
    "KilnCharge",
    "ProductLine",
    "CoreStock",
    "PrefinishLine",
    "FlooringLot",
    "GradeRun",
    "GradeBundle",
    "PrefinishRun",
    "ByproductBatch",
    "ByproductSale",
    "WarrantyClaim",
    "YieldSummary",
]
