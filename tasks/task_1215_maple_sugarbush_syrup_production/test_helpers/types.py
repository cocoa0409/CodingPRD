"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class SeasonStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    RECONCILED = "RECONCILED"


class SugarbushStatus(str, Enum):
    PREP = "PREP"
    TAPPING = "TAPPING"
    LIVE = "LIVE"
    SHUTDOWN = "SHUTDOWN"


class StandType(str, Enum):
    OWNED = "OWNED"
    LEASED = "LEASED"


class LeaseStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_AUDIT = "PENDING_AUDIT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class RoyaltyBasis(str, Enum):
    PER_TAP = "PER_TAP"
    SHARE_OF_SYRUP = "SHARE_OF_SYRUP"


class TapLineStatus(str, Enum):
    INSTALLING = "INSTALLING"
    ACTIVE = "ACTIVE"
    LEAK = "LEAK"
    PULLED = "PULLED"


class WeatherWindowStatus(str, Enum):
    FORECAST = "FORECAST"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class CrewMemberStatus(str, Enum):
    HIRED = "HIRED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"


class CrewRole(str, Enum):
    TAPPER = "TAPPER"
    BOILER = "BOILER"
    GRADER = "GRADER"


class SapRunStatus(str, Enum):
    DRAFT = "DRAFT"
    CONFIRMED = "CONFIRMED"
    VOIDED = "VOIDED"


class EvaporatorBatchStatus(str, Enum):
    FILLING = "FILLING"
    BOILING = "BOILING"
    FINISHED = "FINISHED"
    CANCELLED = "CANCELLED"


class SyrupLotStatus(str, Enum):
    UNGRADED = "UNGRADED"
    GRADED = "GRADED"
    HELD = "HELD"
    CONDEMNED = "CONDEMNED"
    EXHAUSTED = "EXHAUSTED"


class SyrupGrade(str, Enum):
    GOLDEN = "GOLDEN"
    AMBER = "AMBER"
    DARK = "DARK"
    VERY_DARK = "VERY_DARK"
    PROCESSING = "PROCESSING"


class PackagingRunStatus(str, Enum):
    PLANNED = "PLANNED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"


class ContainerType(str, Enum):
    DRUM_55 = "DRUM_55"
    RETAIL_QUART = "RETAIL_QUART"
    RETAIL_PINT = "RETAIL_PINT"


class AuditType(str, Enum):
    ORGANIC = "ORGANIC"
    WOODS = "WOODS"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class CertAuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RECORDED = "RECORDED"


class UserRole(str, Enum):
    SUGARHOUSE_MANAGER = "SugarhouseManager"
    FIELD_CREW = "FieldCrew"
    SUGAR_MAKER = "SugarMaker"
    CERT_INSPECTOR = "CertInspector"


# --- Entity TypedDicts -------------------------------------------------------
# Common resources (PRD §2.4) carry id + created_at + updated_at + version.
# Append-only fact records (VacuumReading, BatchIntake, FlavorEvaluation)
# carry ONLY id + created_at; updated_at and version are absent.


class Season(TypedDict, total=False):
    id: str
    year: int
    opens_on: str
    closes_on: str
    planned_taps: int
    status: str
    taps_live: int
    total_sap_gallons: float
    total_syrup_gallons: float
    created_at: str
    updated_at: str
    version: int


class Sugarbush(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    tap_capacity: int
    stand_type: str
    active_lease_id: Optional[str]
    organic_certified: bool
    taps_set: int
    taps_live: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Lease(TypedDict, total=False):
    id: str
    sugarbush_id: str
    landowner_name: str
    royalty_basis: str
    per_tap_cents: Optional[int]
    share_pct: Optional[float]
    certified_organic_required: bool
    term_start: str
    term_end: str
    status: str
    taps_snapshot: Optional[int]
    accrued_royalty_cents: int
    accrued_royalty_gallons: float
    settled_royalty_gallons: Optional[float]
    created_at: str
    updated_at: str
    version: int


class TapLine(TypedDict, total=False):
    id: str
    sugarbush_id: str
    line_code: str
    tap_count: int
    vacuum_target_inhg: float
    latest_vacuum_inhg: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class VacuumReading(TypedDict, total=False):
    # Append-only: NO updated_at, NO version (PRD §2.4).
    id: str
    tap_line_id: str
    inhg: float
    recorded_at: str
    created_at: str


class WeatherWindow(TypedDict, total=False):
    id: str
    season_id: str
    opens_at: str
    closes_at: str
    forecast_min_f: float
    forecast_max_f: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    season_id: str
    name: str
    crew_role: str
    cert_organic_handler: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SapRun(TypedDict, total=False):
    id: str
    sugarbush_id: str
    weather_window_id: str
    collected_by: str
    gallons_collected: float
    measured_brix: float
    collected_at: str
    gallons_remaining: float
    status: str
    created_at: str
    updated_at: str
    version: int


class EvaporatorBatch(TypedDict, total=False):
    id: str
    season_id: str
    boiled_by: str
    evaporator_capacity_gal: int
    sap_gallons_in: float
    input_brix: Optional[float]
    estimated_syrup_gallons: Optional[float]
    expected_syrup_gallons: Optional[float]
    boil_started_at: Optional[str]
    finished_brix: Optional[float]
    measured_syrup_gallons: Optional[float]
    yield_variance_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class BatchIntake(TypedDict, total=False):
    # Append-only: NO updated_at, NO version (PRD §2.4).
    id: str
    batch_id: str
    sap_run_id: str
    gallons_drawn: float
    draw_sequence: int
    effective_brix: Optional[float]
    created_at: str


class SyrupLot(TypedDict, total=False):
    id: str
    batch_id: str
    season_id: str
    measured_gallons: float
    finished_brix: float
    light_transmittance_pct: Optional[float]
    grade: Optional[str]
    unpackaged_gallons: float
    quality_hold_auto: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FlavorEvaluation(TypedDict, total=False):
    # Append-only: NO updated_at, NO version (PRD §2.4).
    id: str
    syrup_lot_id: str
    evaluator_id: str
    flavor_score: int
    defect_flags: list
    evaluated_at: str
    created_at: str


class PackagingRun(TypedDict, total=False):
    id: str
    syrup_lot_id: str
    container_type: str
    units_planned: int
    units_filled: Optional[int]
    filled_gallons: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class CertAudit(TypedDict, total=False):
    id: str
    sugarbush_id: str
    audit_type: str
    scheduled_for: str
    result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
