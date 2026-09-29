"""Domain vocabulary: roles, enumerations and entity shapes for the plant-ops API.

Every literal in this module is taken from the PRD verbatim, so a test that reads
``PlantStatus.RESTRICTED`` is reading the contract, not a guess.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional, TypedDict


# --------------------------------------------------------------------------- #
# Roles (PRD 2.1)
# --------------------------------------------------------------------------- #


class Role(str, Enum):
    PLANT_ADMIN = "PlantAdmin"
    MATERIALS_CONTROLLER = "MaterialsController"
    PRODUCTION_SCHEDULER = "ProductionScheduler"
    QUALITY_INSPECTOR = "QualityInspector"
    QUALITY_MANAGER = "QualityManager"
    MAINTENANCE_PLANNER = "MaintenancePlanner"
    PLANT_MANAGER = "PlantManager"


ALL_ROLES: tuple[str, ...] = tuple(r.value for r in Role)


# --------------------------------------------------------------------------- #
# Enumerations
# --------------------------------------------------------------------------- #


class ProductionPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class BoardLineStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    MAINTENANCE_SCHEDULED = "MAINTENANCE_SCHEDULED"
    UNDER_MAINTENANCE = "UNDER_MAINTENANCE"


class LotSourceType(str, Enum):
    NATURAL = "NATURAL"
    SYNTHETIC = "SYNTHETIC"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    APPROVED = "APPROVED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    DEPLETED = "DEPLETED"


class QuarantineReason(str, Enum):
    MOISTURE_CEILING = "MOISTURE_CEILING"
    PURITY_FLOOR = "PURITY_FLOOR"
    CHLORIDE_CEILING = "CHLORIDE_CEILING"


class BatchStatus(str, Enum):
    PLANNED = "PLANNED"
    FEEDING = "FEEDING"
    CALCINING = "CALCINING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class StuccoQualityFlag(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"


class StuccoTestResult(str, Enum):
    PASS = "PASS"
    MARGINAL = "MARGINAL"
    FAIL = "FAIL"


class BoardType(str, Enum):
    REGULAR = "REGULAR"
    TYPE_X = "TYPE_X"
    TYPE_C = "TYPE_C"
    MOLD_RESISTANT = "MOLD_RESISTANT"
    ABUSE_RESISTANT = "ABUSE_RESISTANT"


class ChangeoverFamily(str, Enum):
    STANDARD = "STANDARD"
    FIRE_RATED = "FIRE_RATED"
    SPECIALTY = "SPECIALTY"


class RunStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QualityState(str, Enum):
    UNTESTED = "UNTESTED"
    IN_TEST = "IN_TEST"
    RELEASED = "RELEASED"
    DOWNGRADED = "DOWNGRADED"
    HELD = "HELD"
    SCRAPPED = "SCRAPPED"


class SaleableGrade(str, Enum):
    UNGRADED = "UNGRADED"
    FIRST_QUALITY = "FIRST_QUALITY"
    SECONDS = "SECONDS"
    SCRAP = "SCRAP"


class HeldReason(str, Enum):
    EDGE_DEFECT = "EDGE_DEFECT"
    END_DEFECT = "END_DEFECT"
    BOARD_TEST_FAIL = "BOARD_TEST_FAIL"
    MOISTURE_EXCEEDANCE = "MOISTURE_EXCEEDANCE"
    STUCCO_NONCONFORMING = "STUCCO_NONCONFORMING"


class BoardTestResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class FailingAttribute(str, Enum):
    CORE_HARDNESS = "CORE_HARDNESS"
    NAIL_PULL = "NAIL_PULL"
    FLEXURAL_CROSS = "FLEXURAL_CROSS"
    EXIT_MOISTURE = "EXIT_MOISTURE"


class DispositionAction(str, Enum):
    RELEASE = "RELEASE"
    DOWNGRADE = "DOWNGRADE"
    SCRAP = "SCRAP"


class OutageType(str, Enum):
    PLANNED = "PLANNED"
    EMERGENCY = "EMERGENCY"


class OutageStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    DEFERRED = "DEFERRED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class LoadOrderStatus(str, Enum):
    STAGED = "STAGED"
    HELD = "HELD"
    LOADED = "LOADED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class HoldSource(str, Enum):
    RUN_QUALITY_HELD = "RUN_QUALITY_HELD"


class RateZone(str, Enum):
    ZONE_1 = "ZONE_1"
    ZONE_2 = "ZONE_2"
    ZONE_3 = "ZONE_3"
    ZONE_4 = "ZONE_4"


# --------------------------------------------------------------------------- #
# Entity shapes
# --------------------------------------------------------------------------- #


class Plant(TypedDict, total=False):
    id: str
    code: str
    name: str
    calciner_capacity_tph: float
    stucco_silo_capacity_tons: float
    natural_gypsum_purity_floor_pct: float
    synthetic_free_moisture_ceiling_pct: float
    energy_price_per_mmbtu: float
    contribution_margin_per_msf: float
    stucco_on_hand_tons: float
    stucco_committed_tons: float
    stucco_available_tons: float
    held_run_count: int
    production_posture: str
    created_at: str
    updated_at: str
    version: int


class BoardLine(TypedDict, total=False):
    id: str
    plant_id: str
    designation: str
    max_speed_fpm: int
    web_width_in: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductSpec(TypedDict, total=False):
    id: str
    plant_id: str
    sku_code: str
    thickness_in: float
    board_type: str
    fire_rated: bool
    board_width_in: float
    board_length_ft: float
    target_board_weight_lb_per_msf: float
    stucco_lb_per_msf: float
    slurry_water_stucco_ratio: float
    line_speed_max_fpm: int
    paper_tension_min_lb: float
    paper_tension_max_lb: float
    core_hardness_min_lbf: float
    nail_pull_min_lbf: float
    flexural_cross_min_lbf: float
    max_boards_per_bundle: int
    changeover_family: str
    created_at: str
    updated_at: str
    version: int


class Market(TypedDict, total=False):
    id: str
    name: str
    distance_miles: int
    fuel_surcharge_pct: float
    min_charge_usd: float
    backhaul_credit_usd: float
    rate_zone: str
    base_rate_per_msf: float
    created_at: str
    updated_at: str
    version: int


class GypsumLot(TypedDict, total=False):
    id: str
    plant_id: str
    source_type: str
    supplier_name: str
    received_tons: float
    declared_free_moisture_pct: float
    declared_purity_pct: float
    free_moisture_pct: Optional[float]
    purity_pct: Optional[float]
    chloride_ppm: Optional[int]
    assayed_at: Optional[str]
    assay_count: int
    status: str
    quarantine_reason: Optional[str]
    reject_note: Optional[str]
    consumed_tons: float
    remaining_tons: float
    created_at: str
    updated_at: str
    version: int


class CalcinerBatch(TypedDict, total=False):
    id: str
    plant_id: str
    target_stucco_tons: float
    calcination_temp_f: float
    feed_rate_tph: float
    feed_window_start: str
    feed_window_end: str
    status: str
    stucco_quality_flag: str
    feed_tons_total: float
    feed_moisture_plan_pct: Optional[float]
    feed_moisture_as_fed_pct: Optional[float]
    feed_purity_plan_pct: Optional[float]
    stucco_yield_plan_tons: float
    stucco_yield_actual_tons: float
    abort_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BatchFeed(TypedDict, total=False):
    """PRD 2.4: carries only ``id`` and ``created_at`` besides its own payload."""

    id: str
    batch_id: str
    lot_id: str
    feed_seq: int
    tons_fed: float
    measured_free_moisture_pct: float
    assay_free_moisture_pct: float
    assay_purity_pct: float
    dry_tons_plan: float
    dry_tons_as_fed: float
    created_at: str


class StuccoTest(TypedDict, total=False):
    """PRD 2.4: carries only ``id`` and ``created_at``."""

    id: str
    batch_id: str
    sample_seq: int
    combined_water_pct: float
    free_water_pct: float
    set_time_minutes: float
    normal_consistency_cc: float
    result: str
    recorded_by_user_id: str
    tested_at: str
    created_at: str


class ProductionRun(TypedDict, total=False):
    id: str
    plant_id: str
    line_id: str
    product_spec_id: str
    calciner_batch_id: str
    window_start: str
    window_end: str
    requested_planned_msf: float
    line_speed_fpm: int
    paper_tension_lb: float
    kiln_dwell_minutes: int
    kiln_exit_moisture_target_pct: float
    required_paper_tension_lb: float
    projected_exit_moisture_pct: float
    status: str
    quality_state: str
    saleable_grade: str
    prior_run_id: Optional[str]
    changeover_minutes: Optional[int]
    gap_minutes: Optional[int]
    in_window_changeover_minutes: Optional[int]
    available_minutes: Optional[int]
    capacity_msf: Optional[float]
    effective_planned_msf: float
    stucco_reserved_tons: float
    kiln_energy_mmbtu: Optional[float]
    kiln_energy_cost_usd: Optional[float]
    actual_msf: float
    scrap_msf: float
    edge_defect_ppm: Optional[int]
    end_defect_ppm: Optional[int]
    stucco_consumed_tons: float
    net_good_msf: float
    scrapped_msf: float
    available_msf: float
    specimen_count: int
    failing_specimen_count: int
    fail_rate: float
    retest_count: int
    held_reason: Optional[str]
    cancel_reason: Optional[str]
    last_failing_test_recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BoardTest(TypedDict, total=False):
    """PRD 2.4: carries only ``id`` and ``created_at``."""

    id: str
    run_id: str
    specimen_seq: int
    core_hardness_lbf: float
    nail_pull_lbf: float
    flexural_cross_lbf: float
    flexural_parallel_lbf: float
    exit_moisture_pct: float
    result: str
    failing_attributes: list[str]
    recorded_by_user_id: str
    tested_at: str
    created_at: str


class MaintenanceOutage(TypedDict, total=False):
    id: str
    line_id: str
    outage_type: str
    window_start: str
    window_end: str
    scope_note: str
    status: str
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]
    deferred_reason: Optional[str]
    close_note: Optional[str]
    deferral_count: int
    seasonality_index: float
    planned_downtime_hours: float
    at_risk_msf: float
    opportunity_cost_usd: float
    created_at: str
    updated_at: str
    version: int


class LoadOrder(TypedDict, total=False):
    id: str
    run_id: str
    market_id: str
    bundles_count: int
    boards_per_bundle: int
    loaded_bundles_count: Optional[int]
    board_msf_each: float
    bundle_msf: float
    bundle_weight_lb: float
    total_msf: float
    trailer_weight_lb: float
    quoted_freight_usd: float
    settled_freight_usd: Optional[float]
    overweight_fee_usd: Optional[float]
    freight_variance_usd: Optional[float]
    backhaul: bool
    status: str
    hold_source: Optional[str]
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


JsonDict = dict[str, Any]
