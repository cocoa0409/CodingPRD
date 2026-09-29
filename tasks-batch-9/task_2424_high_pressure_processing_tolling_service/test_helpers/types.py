"""Typed shapes for every resource the API returns, plus the enumerations they draw on.

Thirteen resources carry the full set of common properties — ``id``,
``created_at``, ``updated_at`` and ``version``.  Two are append-only event
records that carry only ``id`` and ``created_at``: a lab validation run and a
chamber cycle log.  That split is reflected in the two base TypedDicts below and
is what ``assert_common_fields`` / ``assert_append_only_fields`` check.
"""

from typing import List, Literal, Optional, TypedDict

# --------------------------------------------------------------------------- #
# roles and headers
# --------------------------------------------------------------------------- #
UserRole = Literal[
    "Customer",
    "PlantScheduler",
    "PlantOperator",
    "QualityManager",
    "FacilityAdmin",
]

# --------------------------------------------------------------------------- #
# enumerations
# --------------------------------------------------------------------------- #
CrossContaminationGroup = Literal[
    "RTE_PRODUCE", "RAW_PROTEIN", "DAIRY", "JUICE", "PET_FOOD"
]
PackageFormat = Literal["POUCH", "TRAY_SEALED", "RIGID_BOTTLE", "GLASS"]
VesselStatus = Literal["AVAILABLE", "IN_USE", "MAINTENANCE", "DOWN"]
ColdRoomCapacityState = Literal["NORMAL", "AT_CAPACITY"]
QualificationStatus = Literal[
    "DRAFT",
    "SUBMITTED",
    "UNDER_VALIDATION",
    "QUALIFIED",
    "CHANGES_REQUESTED",
    "EXPIRED",
    "SUPERSEDED",
]
QualificationDecisionOutcome = Literal["QUALIFY", "REQUEST_CHANGES"]
PackageIntegrityResult = Literal["PASS", "MARGINAL", "FAIL"]
RunVerdict = Literal["ACCEPTABLE", "UNACCEPTABLE"]
ContractStatus = Literal["DRAFT", "ACTIVE", "EXHAUSTED", "CLOSED"]
LotCustodyState = Literal[
    "AT_DOCK",
    "IN_COLD_STORAGE",
    "IN_VESSEL",
    "TREATED",
    "SHIPPED",
    "REJECTED_AT_DOCK",
    "DISPOSED",
]
LotReleaseState = Literal["NOT_RELEASED", "ON_HOLD_FOR_TEST", "RELEASED", "REJECTED"]
DockInspectionOutcome = Literal["ACCEPT", "REJECT"]
ReleaseDecisionOutcome = Literal["RELEASE", "HOLD_FOR_TEST", "REJECT"]
CycleState = Literal[
    "SCHEDULED",
    "LOADED",
    "RUNNING",
    "COMPLETED_CLEAN",
    "COMPLETED_DEVIATED",
    "DISPOSITIONED",
    "ABORTED",
    "CANCELLED",
]
LoadDispositionState = Literal[
    "PENDING", "ALLOCATED", "REPROCESSED", "VOIDED", "REJECTED"
]
LoadInspectionState = Literal["PENDING_INSPECTION", "INSPECTED"]
CcpVerdict = Literal["WITHIN_LIMITS", "DEVIATION"]
DeviationFlag = Literal["UNDER_PRESSURE", "SHORT_HOLD", "TEMP_EXCURSION"]
DeviationType = Literal[
    "UNDER_PRESSURE", "SHORT_HOLD", "TEMP_EXCURSION", "PACKAGE_FAILURE_RATE"
]
DeviationSeverity = Literal["MAJOR", "CRITICAL"]
DeviationStatus = Literal[
    "OPEN", "ADJUDICATED_ACCEPT", "ADJUDICATED_REPROCESS", "ADJUDICATED_REJECT"
]
DeviationDisposition = Literal["ACCEPT", "REPROCESS", "REJECT"]
ChargebackParty = Literal["CUSTOMER", "FACILITY"]
ChargebackBasis = Literal["PACKAGE_LEAKER", "REPROCESS", "TAKE_OR_PAY_SHORTFALL"]
ChargebackStatus = Literal["PENDING", "WAIVED"]


# --------------------------------------------------------------------------- #
# common property bases
# --------------------------------------------------------------------------- #
class VersionedResource(TypedDict):
    """The full common set: id, created_at, updated_at and version."""

    id: str
    created_at: str
    updated_at: str
    version: int


class AppendOnlyRecord(TypedDict):
    """An append-only event record: id and created_at only."""

    id: str
    created_at: str


# --------------------------------------------------------------------------- #
# versioned resources
# --------------------------------------------------------------------------- #
class Customer(VersionedResource):
    name: str
    code: str
    billing_email: str
    trailing_leaker_ppm: int
    chargeback_balance_cents: int


class ProductFamily(VersionedResource):
    family_code: str
    cross_contamination_group: CrossContaminationGroup
    max_receipt_temp_c: float
    max_outbound_temp_c: float
    cleanout_minutes: int
    requires_dedicated_cycle: bool


class Vessel(VersionedResource):
    vessel_code: str
    chamber_volume_liters: float
    max_pressure_mpa: float
    pump_ramp_rate_mpa_per_sec: float
    decompression_seconds: int
    basket_count: int
    hourly_operating_cost_cents: int
    status: VesselStatus
    cycles_run_count: int


class ColdRoom(VersionedResource):
    room_code: str
    capacity_pallets: int
    setpoint_c: float
    allowed_family_groups: List[CrossContaminationGroup]
    occupied_pallets: int
    capacity_state: ColdRoomCapacityState


class ProductQualification(VersionedResource):
    customer_id: str
    product_family_id: str
    sku_code: str
    version_label: str
    pressure_mpa: float
    hold_time_seconds: int
    max_water_temp_c: float
    target_log_reduction: float
    package_format: PackageFormat
    package_burst_pressure_mpa: float
    film_thickness_micron: int
    package_suitability_score: float
    supersedes_qualification_id: Optional[str]
    status: QualificationStatus
    revision_round: int
    validation_run_acceptable_count: int
    qualified_at: Optional[str]
    expires_at: Optional[str]


class CapacityContract(VersionedResource):
    customer_id: str
    season_code: str
    window_start: str
    window_end: str
    committed_slots: int
    slot_take_or_pay_cents: int
    priority_rank: int
    peak_window_start: str
    peak_window_end: str
    peak_multiplier: float
    status: ContractStatus
    reserved_slots: int
    consumed_slots: int
    available_slots: int
    shortfall_slots: int
    take_or_pay_cents: int


class Lot(VersionedResource):
    customer_id: str
    qualification_id: str
    cold_room_id: str
    pallet_ref: str
    unit_count: int
    gross_weight_kg: float
    carrier_temp_c: float
    pulp_temp_c: Optional[float]
    ship_by: str
    segregation_group: CrossContaminationGroup
    custody_state: LotCustodyState
    release_state: LotReleaseState
    hold_reason: Optional[str]
    released_by_user_id: Optional[str]
    units_untreated: int
    units_in_vessel: int
    units_treated: int
    units_disposed: int


class VesselCycle(VersionedResource):
    vessel_id: str
    product_family_id: str
    scheduled_start: str
    scheduled_end: str
    target_pressure_mpa: float
    target_hold_seconds: int
    state: CycleState
    baskets_used_total: int
    utilization_pct: float
    estimated_cycle_seconds: int
    estimated_tolling_fee_cents: int
    actual_cycle_seconds: Optional[int]
    actual_tolling_fee_cents: Optional[int]
    started_at: Optional[str]
    dispositioned_at: Optional[str]


class CycleLoad(VersionedResource):
    cycle_id: str
    lot_id: str
    contract_id: str
    baskets_used: int
    units_loaded: int
    disposition_state: LoadDispositionState
    inspection_state: LoadInspectionState
    allocated_fee_cents: Optional[int]
    units_inspected: Optional[int]
    leaker_units: Optional[int]
    leaker_ppm: Optional[int]
    chargeback_party: Optional[ChargebackParty]
    chargeback_cents: int


class Deviation(VersionedResource):
    cycle_id: str
    cycle_log_id: Optional[str]
    cycle_load_id: Optional[str]
    deviation_type: DeviationType
    severity: DeviationSeverity
    worst_shortfall_pct: float
    status: DeviationStatus
    root_cause_code: Optional[str]
    chargeback_party: Optional[ChargebackParty]
    adjudicated_by_user_id: Optional[str]
    adjudicated_at: Optional[str]


class ChargebackLine(VersionedResource):
    customer_id: str
    basis: ChargebackBasis
    amount_cents: int
    status: ChargebackStatus
    cycle_load_id: Optional[str]
    contract_id: Optional[str]
    deviation_id: Optional[str]
    waived_by_user_id: Optional[str]
    waive_reason: Optional[str]


# --------------------------------------------------------------------------- #
# append-only records
# --------------------------------------------------------------------------- #
class ValidationRun(AppendOnlyRecord):
    qualification_id: str
    measured_pressure_mpa: float
    measured_hold_time_seconds: int
    achieved_log_reduction: float
    package_integrity_result: PackageIntegrityResult
    units_tested: int
    leaker_count: int
    run_verdict: RunVerdict
    recorded_by_user_id: str


class CycleLog(AppendOnlyRecord):
    cycle_id: str
    actual_pressure_mpa: float
    actual_hold_seconds: int
    come_up_seconds: int
    water_temp_c: float
    actual_cycle_seconds: int
    deviation_flags: List[DeviationFlag]
    ccp_verdict: CcpVerdict
    logged_by_user_id: str
    logged_at: str


# --------------------------------------------------------------------------- #
# non-resource responses
# --------------------------------------------------------------------------- #
class DayCloseReport(TypedDict):
    expired_qualification_count: int
    customers_rescored: int
    closed_at: str


class ClockEcho(TypedDict):
    current_utc: str
