"""Entity shapes, status vocabularies and the role vocabulary.

Field names mirror the PRD exactly. Entities that carry the common audit
fields expose id/created_at/updated_at/version; InspectionResult carries
only id and created_at.
"""

from typing import Optional, TypedDict


# --------------------------------------------------------------------------
# Role vocabulary
# --------------------------------------------------------------------------
class Role:
    PLANT_MANAGER = "PlantManager"
    PLANT_SCHEDULER = "PlantScheduler"
    BATCH_HOUSE_TECH = "BatchHouseTech"
    MOLD_ENGINEER = "MoldEngineer"
    QUALITY_ENGINEER = "QualityEngineer"
    WAREHOUSE_OPERATOR = "WarehouseOperator"
    CUSTOMER_REP = "CustomerRep"


ALL_ROLES = (
    Role.PLANT_MANAGER,
    Role.PLANT_SCHEDULER,
    Role.BATCH_HOUSE_TECH,
    Role.MOLD_ENGINEER,
    Role.QUALITY_ENGINEER,
    Role.WAREHOUSE_OPERATOR,
    Role.CUSTOMER_REP,
)


# --------------------------------------------------------------------------
# Enumerated vocabularies
# --------------------------------------------------------------------------
class GlassColor:
    FLINT = "FLINT"
    AMBER = "AMBER"
    GREEN = "GREEN"


class MoldFamily:
    NNPB = "NNPB"
    BLOW_BLOW = "BLOW_BLOW"
    PRESS_BLOW = "PRESS_BLOW"


class MoldOwner:
    PLANT = "PLANT"
    CUSTOMER = "CUSTOMER"


class PalletizationStandard:
    EURO = "EURO_1200x800"
    GMA = "GMA_1200x1000"


class FurnacePosture:
    OPERATING = "OPERATING"
    RESTRICTED = "RESTRICTED"
    REBUILD_DUE = "REBUILD_DUE"
    COLD = "COLD"


class CampaignStatus:
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    WIND_DOWN = "WIND_DOWN"
    REBUILD_SCHEDULED = "REBUILD_SCHEDULED"
    CLOSED = "CLOSED"


class ColorChangeStatus:
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class BottleDesignStatus:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    RISK_SIGNED = "RISK_SIGNED"
    APPROVED = "APPROVED"
    OBSOLETE = "OBSOLETE"


class ProgramStatus:
    DRAFT = "DRAFT"
    RISK_ASSESSED = "RISK_ASSESSED"
    PILOT = "PILOT"
    ADOPTED = "ADOPTED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class SavingsTier:
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class MoldSetStatus:
    AVAILABLE = "AVAILABLE"
    MOUNTED = "MOUNTED"
    IN_REPAIR = "IN_REPAIR"
    SCRAPPED = "SCRAPPED"


class FormingMachineStatus:
    IDLE = "IDLE"
    RUNNING = "RUNNING"


class ProductionJobStatus:
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    CANCELLED = "CANCELLED"


class JobOutcome:
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class LotQualityStatus:
    PENDING_INSPECTION = "PENDING_INSPECTION"
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    SCRAPPED = "SCRAPPED"


class LotLogisticsStatus:
    IN_AGING = "IN_AGING"
    PALLETIZED = "PALLETIZED"
    SHIPPED = "SHIPPED"
    RETURNED = "RETURNED"


class DefectClass:
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ComplaintStatus:
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    CREDIT_ISSUED = "CREDIT_ISSUED"
    REJECTED = "REJECTED"


class ComplaintAttribution:
    UNDETERMINED = "UNDETERMINED"
    PLANT = "PLANT"
    CUSTOMER = "CUSTOMER"
    SHARED = "SHARED"


class Settlement:
    CREDIT = "CREDIT"
    REJECT = "REJECT"


class CustomerDecision:
    PILOT = "PILOT"
    REJECT = "REJECT"


class QualityStanding:
    GOOD = "GOOD"
    WATCH = "WATCH"
    CRITICAL = "CRITICAL"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Furnace(TypedDict):
    id: str
    code: str
    design_pull_tpd: float
    refractory_life_total_units: float
    current_color: str
    refractory_consumed_units: float
    refractory_remaining_pct: float
    posture: str
    reserved_pull_tons: float
    campaign_count: int
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict):
    id: str
    furnace_id: str
    code: str
    status: str
    target_pull_tpd: float
    window_start_at: str
    window_end_at: str
    rebuild_window_start_at: Optional[str]
    rebuild_window_end_at: Optional[str]
    projected_refractory_units_nominal: float
    melt_tons_charged: float
    packed_tons: float
    reject_loss_tons: float
    transition_loss_tons: float
    unaccounted_loss_tons: float
    created_at: str
    updated_at: str
    version: int


class BatchRecipe(TypedDict):
    id: str
    furnace_id: str
    code: str
    color: str
    cullet_ratio_pct: float
    soda_ash_kg_per_ton: float
    colorant_kg_per_ton: float
    cullet_stress_factor: float
    approved: bool
    created_at: str
    updated_at: str
    version: int


class ColorChange(TypedDict):
    id: str
    furnace_id: str
    status: str
    from_color: str
    to_color: str
    window_start_at: str
    window_end_at: str
    transition_loss_tons: float
    created_at: str
    updated_at: str
    version: int


class FormingMachine(TypedDict):
    id: str
    furnace_id: str
    code: str
    status: str
    section_count: int
    max_cavities: int
    mounted_cavities: int
    primary_mold_family: str
    changeover_buffer_minutes: int
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    name: str
    account_code: str
    palletization_standard: str
    complaint_ppm_threshold: float
    weighted_breakage_ppm: float
    quality_standing: str
    credit_issued_usd: float
    created_at: str
    updated_at: str
    version: int


class BottleDesign(TypedDict):
    id: str
    customer_id: str
    code: str
    status: str
    color: str
    capacity_ml: float
    nominal_weight_g: float
    min_wall_thickness_mm: float
    cavity_count: int
    target_line_speed_bpm: float
    container_price_usd: float
    mold_owner: str
    supersedes_design_id: Optional[str]
    breakage_risk_index: float
    lead_time_days: int
    revision_count: int
    risk_signed_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LightweightingProgram(TypedDict):
    id: str
    baseline_design_id: str
    code: str
    status: str
    target_weight_g: float
    annual_volume_units: int
    resin_free_glass_price_per_kg: float
    weight_saved_g: float
    gross_savings_usd: float
    savings_tier: str
    breakage_risk_delta: float
    risk_reserve_usd: float
    net_savings_usd: float
    customer_rebate_usd: float
    pilot_decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionJob(TypedDict):
    id: str
    campaign_id: str
    furnace_id: str
    forming_machine_id: str
    batch_recipe_id: str
    bottle_design_id: str
    mold_set_id: Optional[str]
    code: str
    status: str
    window_start_at: str
    window_end_at: str
    planned_pull_tpd: float
    reserved_melt_tons: float
    produced_units: int
    changeover_minutes: int
    outcome_note: Optional[str]
    projected_refractory_units_nominal: float
    projected_refractory_units_stress_adjusted: float
    refractory_wear_units: float
    created_at: str
    updated_at: str
    version: int


class MoldSet(TypedDict):
    id: str
    bottle_design_id: str
    code: str
    status: str
    cavity_count: int
    mold_family: str
    owner: str
    condition_score: int
    mount_count: int
    forming_machine_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackLot(TypedDict):
    id: str
    production_job_id: str
    campaign_id: str
    bottle_design_id: str
    customer_id: str
    lot_code: str
    quality_status: str
    logistics_status: str
    packed_units: int
    unit_weight_g: float
    reject_units: int
    net_packed_units: int
    major_ppm: float
    minor_ppm: float
    provisional_yield_pct: float
    final_yield_pct: float
    palletization_standard: str
    pallet_count: int
    aged_until_at: str
    shipped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InspectionResult(TypedDict):
    """The one entity without the common audit block: no updated_at, no version."""

    id: str
    pack_lot_id: str
    defect_class: str
    defect_code: str
    rejected_units: int
    inspected_at: str
    recorded_by_user_id: str
    created_at: str


class Complaint(TypedDict):
    id: str
    customer_id: str
    pack_lot_id: str
    code: str
    status: str
    reported_at: str
    affected_units: int
    filling_line_speed_bpm: float
    breakage_ppm: float
    attribution: str
    affected_pallets: int
    credit_usd: float
    findings: Optional[str]
    investigated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
