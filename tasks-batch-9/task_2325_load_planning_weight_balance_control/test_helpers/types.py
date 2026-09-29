"""TypedDict shapes and enum literals for the load planning / weight & balance API.

Every persisted entity carries the four system fields ``id``, ``created_at``,
``updated_at`` and ``version``, so each entity TypedDict below inherits from
:class:`CommonFields`.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

UserRole = Literal[
    "LoadControlAdmin",
    "LoadController",
    "RampAgent",
    "DangerousGoodsOfficer",
    "Captain",
    "AuditInspector",
]

ALL_ROLES: List[str] = [
    "LoadControlAdmin",
    "LoadController",
    "RampAgent",
    "DangerousGoodsOfficer",
    "Captain",
    "AuditInspector",
]

# ---------------------------------------------------------------------------
# Enum literals
# ---------------------------------------------------------------------------

AircraftStatus = Literal["IN_SERVICE", "GROUNDED"]
RunwayStatus = Literal["OPEN", "CLOSED"]
WeightProgramStatus = Literal["ACTIVE", "WITHDRAWN"]
ProgramKind = Literal["STANDARD", "ACTUAL"]

CompartmentKind = Literal["CABIN_ZONE", "HOLD"]

RunwayCondition = Literal["DRY", "WET", "CONTAMINATED"]

FlightStatus = Literal[
    "PLANNING",
    "LOAD_CONTROLLED",
    "DEPARTED",
    "CLOSED",
    "CANCELLED",
]
LoadReleaseState = Literal["OPEN", "HELD_FOR_DG", "RELEASED"]
LimitingFactor = Literal["PERFORMANCE", "MTOW", "MZFW", "MLW", "MAX_TAXI"]

LoadPlanStatus = Literal[
    "DRAFT",
    "COMPUTED",
    "RESTRICTED",
    "SHEET_ISSUED",
    "SUPERSEDED",
]
RestrictionStatus = Literal["UNRESTRICTED", "WEIGHT_RESTRICTED"]
GateBagPolicy = Literal["ABSORB_INTO_UNDERLOAD", "DEFER_ALL"]
OffloadStrategy = Literal["PRIORITY_FIRST", "FEWEST_PIECES"]
RoundingMode = Literal["PER_LINE_THEN_SUM", "SUM_THEN_ROUND"]

CargoItemKind = Literal["GENERAL", "COMPANY", "MAIL", "GATE_BAG"]
CargoItemStatus = Literal[
    "BOOKED",
    "ACCEPTED",
    "LOADED",
    "OFFLOADED",
    "DEFERRED",
    "REJECTED",
]

ImoClass = Literal["CLASS_1", "CLASS_2", "CLASS_3", "CLASS_5", "CLASS_8"]
PackingGroup = Literal["I", "II", "III"]
SegregationGroup = Literal["FLAMMABLE", "OXIDISER", "CORROSIVE", "INERT"]
DeclarationStatus = Literal["SUBMITTED", "ACCEPTED", "REJECTED"]

LoadSheetStatus = Literal["ISSUED", "ACCEPTED", "REJECTED_BY_CAPTAIN", "AMENDED", "SUPERSEDED"]

LmcChangeKind = Literal["PAX_ADD", "PAX_REMOVE", "BAG_ADD", "BAG_REMOVE", "CARGO_OFFLOAD"]
LmcStatus = Literal["APPLIED", "REVERSED"]

AuditBasis = Literal["DOCUMENTED_BASIS", "FINAL_BASIS"]
AuditSeverity = Literal["NONE", "MINOR", "MAJOR", "CRITICAL"]
AuditStatus = Literal["OPEN", "INVESTIGATING", "CLOSED"]


# ---------------------------------------------------------------------------
# System fields
# ---------------------------------------------------------------------------


class CommonFields(TypedDict):
    """The four system-managed fields carried by every entity in this API."""

    id: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class Aircraft(CommonFields, total=False):
    registration: str
    type_code: str
    basic_empty_weight_kg: float
    basic_index: float
    max_takeoff_weight_kg: float
    max_landing_weight_kg: float
    max_zero_fuel_weight_kg: float
    max_taxi_weight_kg: float
    ref_arm_m: float
    lemac_m: float
    mac_length_m: float
    index_c: float
    index_k: float
    fuel_arm_m: float
    seat_count: int
    zfw_fwd_limit_pct_mac: float
    zfw_aft_limit_pct_mac: float
    tow_fwd_limit_pct_mac: float
    tow_aft_limit_pct_mac: float
    tow_knee_weight_kg: float
    tow_aft_knee_adjust_pct_mac: float
    status: AircraftStatus


class Compartment(CommonFields, total=False):
    aircraft_id: str
    code: str
    kind: CompartmentKind
    arm_m: float
    max_weight_kg: float
    running_load_limit_kg_per_m: float
    length_m: float
    seat_capacity: int


class Runway(CommonFields, total=False):
    airport_code: str
    designator: str
    elevation_ft: float
    length_m: float
    slot_capacity_per_window: int
    status: RunwayStatus


class PerformanceBand(CommonFields, total=False):
    runway_id: str
    aircraft_type_code: str
    temp_lo_c: float
    temp_hi_c: float
    base_limit_weight_kg: float


class WeightProgram(CommonFields, total=False):
    code: str
    program_kind: ProgramKind
    male_kg: float
    female_kg: float
    child_kg: float
    infant_kg: float
    checked_bag_kg: float
    documentation_ref: str
    status: WeightProgramStatus


class Flight(CommonFields, total=False):
    flight_number: str
    aircraft_id: str
    departure_runway_id: str
    weight_program_id: str
    scheduled_off_block_utc: str
    scheduled_on_block_utc: str
    crew_weight_kg: float
    crew_arm_m: float
    ramp_fuel_kg: float
    taxi_fuel_kg: float
    trip_fuel_kg: float
    outside_air_temp_c: float
    headwind_component_kt: float
    runway_condition: RunwayCondition
    status: FlightStatus
    load_release_state: LoadReleaseState
    dry_operating_weight_kg: float
    dry_operating_index: float
    performance_limited_takeoff_weight_kg: float
    allowed_payload_kg: float
    limiting_factor: LimitingFactor
    dg_hold_count: int


class LoadPlan(CommonFields, total=False):
    flight_id: str
    revision_no: int
    status: LoadPlanStatus
    gate_bag_policy: GateBagPolicy
    offload_strategy: OffloadStrategy
    rounding_mode: RoundingMode
    base_payload_kg: float
    frozen_underload_kg: float
    restriction_status: RestrictionStatus
    planned_payload_kg: float
    deferred_bag_weight_kg: float
    zero_fuel_weight_kg: float
    index_zfw: float
    mac_zfw_pct: float
    takeoff_weight_kg: float
    index_tow: float
    mac_tow_pct: float
    taxi_weight_kg: float
    landing_weight_kg: float
    underload_kg: float
    envelope_ok: bool


class PaxDistributionLine(CommonFields, total=False):
    load_plan_id: str
    compartment_id: str
    male_count: int
    female_count: int
    child_count: int
    infant_count: int
    actual_weight_kg: Optional[float]
    line_weight_kg: float
    index_delta: float


class BagAllocation(CommonFields, total=False):
    load_plan_id: str
    compartment_id: str
    bag_count: int
    bag_weight_kg: Optional[float]
    effective_weight_kg: float
    index_delta: float


class CargoItem(CommonFields, total=False):
    flight_id: str
    awb_number: str
    item_kind: CargoItemKind
    weight_kg: float
    length_m: float
    is_dangerous_goods: bool
    assigned_compartment_id: Optional[str]
    offload_priority_rank: int
    status: CargoItemStatus


class HazmatDeclaration(CommonFields, total=False):
    cargo_item_id: str
    un_number: str
    imo_class: ImoClass
    packing_group: PackingGroup
    segregation_group: SegregationGroup
    quantity_kg: float
    status: DeclarationStatus
    accepted_by_user_id: Optional[str]
    notoc_issued: bool


class LoadSheet(CommonFields, total=False):
    load_plan_id: str
    sheet_no: int
    status: LoadSheetStatus
    issued_by_user_id: str
    accepted_by_user_id: Optional[str]
    notoc_reference: Optional[str]
    weight_program_documentation_ref: str
    issued_takeoff_weight_kg: float
    issued_index_tow: float
    issued_payload_kg: float
    lmc_allowance_kg: float
    lmc_net_weight_delta_kg: float
    lmc_absolute_weight_delta_kg: float
    final_takeoff_weight_kg: float
    final_index_tow: float
    final_mac_tow_pct: float
    final_payload_kg: float


class LastMinuteChange(CommonFields, total=False):
    load_sheet_id: str
    change_kind: LmcChangeKind
    compartment_id: str
    male_count: int
    female_count: int
    mass_kg: float
    weight_delta_kg: float
    index_delta: float
    status: LmcStatus


class LoadAudit(CommonFields, total=False):
    flight_id: str
    basis: AuditBasis
    actual_pax_weight_kg: float
    actual_bag_weight_kg: float
    actual_cargo_weight_kg: float
    pax_delta_kg: float
    bag_delta_kg: float
    cargo_delta_kg: float
    total_absolute_discrepancy_kg: float
    severity: AuditSeverity
    status: AuditStatus
    closed_by_user_id: Optional[str]
    finding_note: Optional[str]


class OffloadPreview(TypedDict, total=False):
    """Read-only projection returned by the offload preview endpoint."""

    strategy: OffloadStrategy
    excess_weight_kg: float
    offloaded_total_kg: float
    offloaded_piece_count: int
    offloaded_awb_numbers: List[str]


class ClockState(TypedDict, total=False):
    current_utc: str


# Loose alias used where a helper accepts any decoded response payload.
JsonDict = Dict[str, Any]
