"""Typed shapes for the Fiberglass Insulation Manufacturing API.

Every TypedDict mirrors one entity from the PRD's data model. Entities that
carry the common fields expose id/created_at/updated_at/version;
CertificationProgram is immutable and therefore carries only id/created_at
("A CertificationProgram is immutable once created and therefore carries no
updated_at and no version." - PRD 2.4).
"""

from typing import Any, Dict, List, Literal, Optional, TypedDict

# --- Roles -------------------------------------------------------------------

UserRole = Literal[
    "CorporateOps",
    "PlantOperator",
    "QualityEngineer",
    "CertificationOfficer",
    "EnvironmentalCompliance",
    "ChannelManager",
    "ChannelBuyer",
]

# --- Enumerations ------------------------------------------------------------

MeltPosture = Literal["OPEN", "RESTRICTED", "FROZEN"]
PostureReason = Literal[
    "CULLET_FRACTION_AT_RESTRICT_LEVEL",
    "EMISSIONS_EXCEEDANCE",
    "MANUAL_OVERRIDE",
]
EmissionsStatus = Literal["COMPLIANT", "REPORTED", "EXCEEDANCE"]
ConformanceBasis = Literal["PER_SPECIMEN", "LOT_MEAN"]
BinderStatus = Literal[
    "DRAFT",
    "SUBMITTED",
    "EMISSIONS_TESTING",
    "CERTIFIED",
    "REVISION_REQUIRED",
    "SUSPENDED",
    "WITHDRAWN",
]
ProductForm = Literal["BATT", "ROLL"]
FacingType = Literal["UNFACED", "KRAFT", "FSK", "FOIL"]
CertificationStatus = Literal[
    "DRAFT",
    "PENDING_CERTIFICATION",
    "CERTIFIED",
    "DERATED",
    "SUSPENDED",
    "WITHDRAWN",
]
RunStatus = Literal[
    "SCHEDULED", "HELD", "MELTING", "CURING", "PACKAGED", "CLOSED", "ABORTED"
]
QcStatus = Literal[
    "UNSAMPLED", "SAMPLED", "CONFORMING", "NONCONFORMING", "RETEST_PENDING"
]
ChangeoverStatus = Literal["OPEN", "CLOSED"]
ThermalTestStatus = Literal["REQUESTED", "IN_LAB", "COMPLETED", "EXHAUSTED"]
ConformanceVerdict = Literal["CONFORMING", "NONCONFORMING"]
LotStatus = Literal[
    "AVAILABLE", "ALLOCATED", "QUARANTINED", "REPACKED", "CONSUMED", "SCRAPPED"
]
AllocationBasis = Literal["CONTRACT_FIRST", "PRO_RATA"]
CycleStatus = Literal["OPEN", "PROPOSED", "COMMITTED", "CANCELLED"]
ChannelType = Literal["DISTRIBUTOR", "RETAIL"]
PriorityTier = Literal["CONTRACT", "PROGRAM", "SPOT"]
OrderStatus = Literal[
    "SUBMITTED", "ALLOCATED", "PARTIAL", "BACKORDERED", "SHIPPED", "CANCELLED"
]
AllocationLineStatus = Literal["PROPOSED", "ALLOCATED", "REVOKED"]
CulletSourceType = Literal["TRIM", "CHANGEOVER_SCRAP", "QUARANTINE_SCRAP", "EXTERNAL"]
CulletStatus = Literal["STAGED", "CHARGED", "REJECTED"]

BinderDecision = Literal["CERTIFY", "REQUEST_REVISION", "SUSPEND", "WITHDRAW"]
SkuDecision = Literal[
    "CERTIFY", "DERATE", "REJECT", "SUSPEND", "REINSTATE", "WITHDRAW"
]
PostureDecision = Literal["RECOMPUTE", "OVERRIDE_TO_OPEN"]
QuarantineDisposition = Literal["HOLD", "SCRAP"]

# --- Common field mixins -----------------------------------------------------


class VersionedEntity(TypedDict):
    """id/created_at/updated_at/version carried by every mutable entity."""

    id: str
    created_at: str
    updated_at: str
    version: int


class ImmutableEntity(TypedDict):
    """id/created_at only - for entities the PRD declares immutable."""

    id: str
    created_at: str


# --- Entities ----------------------------------------------------------------


class Plant(VersionedEntity, total=False):
    name: str
    site_code: str
    oven_zone_count: int
    oven_length_ft: float
    production_line_count: int
    max_cullet_fraction: float
    cullet_restrict_fraction: float
    max_width_change_in: float
    permit_number: str
    formaldehyde_allowance_kg: float
    voc_allowance_kg: float
    cullet_received_kg_ytd: float
    cullet_on_hand_kg: float
    cullet_charged_kg_ytd: float
    cullet_rejected_kg_ytd: float
    total_charge_kg_ytd: float
    cullet_fraction_ytd: float
    melt_posture: MeltPosture
    posture_reason: Optional[PostureReason]
    emissions_status: EmissionsStatus
    reported_formaldehyde_kg: float
    reported_voc_kg: float
    reported_period_start: Optional[str]
    reported_period_end: Optional[str]
    override_reason: Optional[str]


class CertificationProgram(ImmutableEntity, total=False):
    code: str
    conformance_basis: ConformanceBasis
    r_value_tolerance: float
    min_specimen_count: int
    max_concurrent_lab_tests: int
    retest_limit: int
    derate_allowed: bool


class BinderFormulation(VersionedEntity, total=False):
    code: str
    formaldehyde_free: bool
    formaldehyde_ppm: float
    voc_g_per_kg: float
    min_cure_temp_f: float
    min_dwell_s: float
    loi_target_pct: float
    status: BinderStatus
    emissions_cert_id: Optional[str]
    lab_reference: Optional[str]
    revision_notes: Optional[str]
    revision_count: int
    certified_at: Optional[str]


class ProductLine(VersionedEntity, total=False):
    sku: str
    plant_id: str
    binder_formulation_id: str
    certification_program_id: str
    form: ProductForm
    density_pcf: float
    facing_type: FacingType
    width_in: float
    thickness_in: float
    declared_r_value: float
    bag_sqft: float
    bale_volume_ft3: float
    bale_mass_kg: float
    compression_ratio: float
    mass_rate_kg_per_min: float
    certification_status: CertificationStatus
    effective_declared_r_value: Optional[float]
    nonconformance_count: int
    recovered_thickness_pct: float
    compressed_bale_volume_ft3: float
    bales_per_truck: int
    freight_cost_per_sqft: float
    recovery_penalty_per_sqft: float
    net_landed_cost_per_sqft: float
    certified_by_user_id: Optional[str]


class ProductionRun(VersionedEntity, total=False):
    plant_id: str
    product_line_id: str
    line_index: int
    scheduled_start: str
    scheduled_end: str
    target_pull_kg: float
    zone_setpoints_f: List[float]
    avg_zone_temp_f: Optional[float]
    line_speed_fpm: Optional[float]
    binder_applied_kg: Optional[float]
    bags_produced: Optional[int]
    total_charge_kg: Optional[float]
    allowed_cullet_kg: Optional[float]
    cullet_charged_kg: float
    virgin_batch_kg: Optional[float]
    cullet_fraction: Optional[float]
    dwell_s: Optional[float]
    cure_index: Optional[float]
    produced_sqft: Optional[float]
    changeover_scrap_kg: float
    formaldehyde_kg: Optional[float]
    voc_kg: Optional[float]
    run_status: RunStatus
    qc_status: QcStatus
    hold_reason: Optional[str]
    closed_at: Optional[str]


class ChangeoverEvent(VersionedEntity, total=False):
    plant_id: str
    outgoing_run_id: str
    incoming_run_id: str
    line_index: int
    window_start: str
    window_end: str
    from_density_pcf: float
    to_density_pcf: float
    from_width_in: float
    to_width_in: float
    facing_changed: bool
    density_delta_pct: float
    purge_minutes: float
    provisional_scrap_kg: float
    weighed_trim_kg: Optional[float]
    recovered_cullet_kg: Optional[float]
    reconciled_scrap_kg: Optional[float]
    scrap_variance_kg: Optional[float]
    status: ChangeoverStatus


class ThermalTest(VersionedEntity, total=False):
    production_run_id: str
    product_line_id: str
    certification_program_id: str
    window_start: str
    window_end: str
    specimen_r_values: List[float]
    conformance_basis: ConformanceBasis
    declared_r_value_at_test: float
    specimen_count: int
    mean_r_value: Optional[float]
    min_r_value: Optional[float]
    conformance_verdict: Optional[ConformanceVerdict]
    attempt_number: int
    recorded_by_user_id: Optional[str]
    status: ThermalTestStatus


class InventoryLot(VersionedEntity, total=False):
    plant_id: str
    product_line_id: str
    production_run_id: str
    parent_lot_id: Optional[str]
    form: ProductForm
    bags: int
    produced_sqft: float
    allocated_sqft: float
    available_sqft: float
    status: LotStatus
    quarantine_reason: Optional[str]


class AllocationCycle(VersionedEntity, total=False):
    plant_id: str
    product_line_id: str
    period_start: str
    period_end: str
    allocation_basis: AllocationBasis
    peak_season: bool
    total_available_sqft: Optional[float]
    seasonal_reserve_sqft: Optional[float]
    allocatable_sqft: Optional[float]
    total_requested_sqft: Optional[float]
    shortage_ratio: Optional[float]
    allocated_sqft: float
    unallocated_sqft: Optional[float]
    status: CycleStatus


class ChannelOrder(VersionedEntity, total=False):
    product_line_id: str
    channel_type: ChannelType
    priority_tier: PriorityTier
    requested_sqft: float
    required_by: str
    placed_by_user_id: str
    allocated_sqft: float
    fill_rate_pct: float
    status: OrderStatus


class AllocationLine(VersionedEntity, total=False):
    allocation_cycle_id: str
    channel_order_id: str
    inventory_lot_id: str
    allocated_sqft: float
    bags: int
    status: AllocationLineStatus
    revoke_reason: Optional[str]


class CulletBatch(VersionedEntity, total=False):
    plant_id: str
    source_run_id: Optional[str]
    charged_run_id: Optional[str]
    source_type: CulletSourceType
    mass_kg: float
    status: CulletStatus
    reject_reason: Optional[str]


# --- Envelope ----------------------------------------------------------------


class ResponseMeta(TypedDict, total=False):
    total: int
    limit: int
    offset: int


class ApiEnvelope(TypedDict, total=False):
    success: bool
    data: Any
    meta: ResponseMeta


JsonDict = Dict[str, Any]
