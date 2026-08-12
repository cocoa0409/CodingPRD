"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    DISPATCHER = "Dispatcher"
    CAPTAIN = "Captain"
    DISPATCH_SUPERVISOR = "DispatchSupervisor"


class StationStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class DeskShiftStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


class LegOpsStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    DIVERTED = "DIVERTED"
    CANCELLED = "CANCELLED"


class MonitorStatus(str, Enum):
    UNMONITORED = "UNMONITORED"
    MONITORING = "MONITORING"
    ALERTED = "ALERTED"
    CLOSED = "CLOSED"


class PlanStatus(str, Enum):
    COMPUTED = "COMPUTED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class WindAssumption(str, Enum):
    FORECAST = "FORECAST"
    WORST_CASE = "WORST_CASE"


class MelCategory(str, Enum):
    MEL = "MEL"
    CDL = "CDL"


class DeferralCategory(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class MelStatus(str, Enum):
    OPEN = "OPEN"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"


class WeatherStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class ReleaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_SIGNATURES = "PENDING_SIGNATURES"
    RELEASED = "RELEASED"
    UNDER_AMENDMENT = "UNDER_AMENDMENT"
    CANCELLED = "CANCELLED"
    CLOSED = "CLOSED"


class SignerRole(str, Enum):
    DISPATCHER = "DISPATCHER"
    CAPTAIN = "CAPTAIN"


class Recommendation(str, Enum):
    NONE = "NONE"
    CONSIDER_DIVERT = "CONSIDER_DIVERT"
    RECOMMEND_DIVERT = "RECOMMEND_DIVERT"


class MonitoringEventStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class ControlAction(str, Enum):
    LEG_CREATED = "LEG_CREATED"
    DELAY_DECISION = "DELAY_DECISION"
    CANCEL_DECISION = "CANCEL_DECISION"
    DEPARTURE = "DEPARTURE"
    ARRIVAL = "ARRIVAL"
    DIVERSION = "DIVERSION"
    RELEASE_CREATED = "RELEASE_CREATED"
    RELEASE_SUBMITTED = "RELEASE_SUBMITTED"
    SIGNATURE_RECORDED = "SIGNATURE_RECORDED"
    RELEASE_RECALLED = "RELEASE_RECALLED"
    RELEASE_AMENDED = "RELEASE_AMENDED"
    RELEASE_AUTO_AMENDED = "RELEASE_AUTO_AMENDED"
    DIVERT_RECOMMENDED = "DIVERT_RECOMMENDED"
    MEL_EXPIRED = "MEL_EXPIRED"


# --- Entities carrying id + created_at + updated_at + version (PRD §2.5) ---


class Station(TypedDict, total=False):
    id: str
    iata_code: str
    runway_length_m: int
    alternate_distance_nm: int
    min_ceiling_ft: int
    min_visibility_m: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict, total=False):
    id: str
    tail_no: str
    type_code: str
    oew_kg: int
    mzfw_kg: int
    mtow_kg: int
    mlw_kg: int
    fuel_capacity_kg: int
    cruise_tas_kts: int
    burn_kg_per_hour: int
    min_runway_m: int
    lemac_m: float
    mac_m: float
    created_at: str
    updated_at: str
    version: int


class Dispatcher(TypedDict, total=False):
    id: str
    name: str
    license_no: str
    max_active_legs: int
    workload_leg_count: int
    weighted_load_score: int
    created_at: str
    updated_at: str
    version: int


class Captain(TypedDict, total=False):
    id: str
    name: str
    license_no: str
    qualified_type_codes: list
    created_at: str
    updated_at: str
    version: int


class Desk(TypedDict, total=False):
    id: str
    code: str
    region: str
    max_dispatchers: int
    active_shift_count: int
    free_slots: int
    created_at: str
    updated_at: str
    version: int


class DeskShift(TypedDict, total=False):
    id: str
    dispatcher_id: str
    desk_id: str
    shift_start_utc: str
    shift_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FlightLeg(TypedDict, total=False):
    id: str
    flight_no: str
    dep_station_id: str
    arr_station_id: str
    aircraft_id: str
    captain_id: str
    dispatcher_id: str
    diverted_from_leg_id: Optional[str]
    distance_nm: int
    sched_dep_utc: str
    sched_arr_utc: str
    actual_dep_utc: Optional[str]
    ops_status: str
    monitor_status: str
    delay_count: int
    created_at: str
    updated_at: str
    version: int


class FlightPlan(TypedDict, total=False):
    id: str
    leg_id: str
    plan_seq: int
    route_code: str
    cruise_altitude_ft: int
    forecast_wind_kts: int
    wind_assumption: str
    status: str
    ground_speed_kts: int
    trip_time_min: int
    burn_eff_kg_per_hour: int
    trip_fuel_kg: int
    mel_fuel_penalty_kg: int
    contingency_kg: int
    alternate_fuel_kg: int
    final_reserve_kg: int
    required_fuel_kg: int
    alternate_station_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayloadManifest(TypedDict, total=False):
    id: str
    leg_id: str
    plan_id: str
    pax_count: int
    bags_count: int
    cargo_kg: float
    pax_weight_kg: int
    baggage_kg: int
    cargo_billed_kg: int
    total_payload_kg: int
    zero_fuel_weight_kg: int
    takeoff_weight_kg: int
    landing_weight_kg: int
    cg_percent_mac: float
    max_payload_kg: int
    created_at: str
    updated_at: str
    version: int


class MelCdlItem(TypedDict, total=False):
    id: str
    aircraft_id: str
    item_code: str
    category: str
    deferral_category: str
    fuel_penalty_pct: float
    payload_penalty_kg: int
    minima_bump: bool
    repair_deadline_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherPackage(TypedDict, total=False):
    id: str
    station_id: str
    valid_from_utc: str
    valid_to_utc: str
    ceiling_ft: int
    visibility_m: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FlightRelease(TypedDict, total=False):
    id: str
    leg_id: str
    plan_id: str
    dispatcher_id: str
    captain_id: str
    status: str
    cycle_seq: int
    amendment_count: int
    created_at: str
    updated_at: str
    version: int


class MonitoringEvent(TypedDict, total=False):
    id: str
    leg_id: str
    fuel_remaining_kg: int
    eta_destination_utc: str
    dest_ceiling_ft: Optional[int]
    dest_visibility_m: Optional[int]
    projected_arrival_fuel_kg: int
    fuel_margin_kg: int
    recommendation: str
    status: str
    created_at: str
    updated_at: str
    version: int


# --- Append-only records: ONLY id + created_at (PRD §2.5) ---


class ReleaseSignature(TypedDict, total=False):
    id: str
    release_id: str
    signer_role: str
    signer_id: str
    cycle_seq: int
    signed_at_utc: str
    created_at: str


class OperationalControlRecord(TypedDict, total=False):
    id: str
    leg_id: str
    release_id: Optional[str]
    actor_role: str
    actor_id: Optional[str]
    action: str
    from_status: Optional[str]
    to_status: Optional[str]
    note: Optional[str]
    recorded_at_utc: str
    created_at: str
