"""Domain types: entity TypedDicts, status enums, role enum.

Entities carrying the standard system-managed property set expose
id + created_at + updated_at + version. The three immutable telemetry
records (SimulationRun, WeatherReading, FlightLog) carry only id and
created_at — no updated_at, no version.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class ShowLifecycleStatus(str, Enum):
    PLANNING = "PLANNING"
    DESIGN_LOCKED = "DESIGN_LOCKED"
    AUTHORIZED = "AUTHORIZED"
    READY = "READY"
    GO_CERTIFIED = "GO_CERTIFIED"
    EXECUTED = "EXECUTED"
    POSTPONED = "POSTPONED"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    DEPOSIT_DUE = "DEPOSIT_DUE"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    REFUNDED = "REFUNDED"


class CancellationStatus(str, Enum):
    NONE = "NONE"
    FILED = "FILED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class CancellationTier(str, Enum):
    T1_FULL = "T1_FULL"
    T2_DEPOSIT_HALF = "T2_DEPOSIT_HALF"
    T3_BALANCE_ONLY = "T3_BALANCE_ONLY"
    T4_HALF_ALL = "T4_HALF_ALL"


class ReadinessPosture(str, Enum):
    NOT_READY = "NOT_READY"
    CLEARED = "CLEARED"
    GO = "GO"


class AuthorizationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    SIMULATED = "SIMULATED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class SimulationVerdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SafetyConfigStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"


class DroneStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    CHARGING = "CHARGING"
    RESERVED = "RESERVED"
    IN_MAINTENANCE = "IN_MAINTENANCE"
    GROUNDED = "GROUNDED"
    RETIRED = "RETIRED"


class ChargeSessionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    INTERRUPTED = "INTERRUPTED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    VOIDED = "VOIDED"
    FLOWN = "FLOWN"
    RECONCILED = "RECONCILED"


class EvaluationVerdict(str, Enum):
    GO = "GO"
    NO_GO = "NO_GO"


class EvaluationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentSource(str, Enum):
    MANUAL = "MANUAL"
    AUTO_DEVIATION = "AUTO_DEVIATION"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    CLOSED_CONFIRMED = "CLOSED_CONFIRMED"
    CLOSED_REJECTED = "CLOSED_REJECTED"


class FlightLogFlag(str, Enum):
    RECEIVED = "RECEIVED"
    FLAGGED = "FLAGGED"


class LostLinkAction(str, Enum):
    HOVER_THEN_LAND = "HOVER_THEN_LAND"
    RETURN_TO_HOME = "RETURN_TO_HOME"
    IMMEDIATE_LAND = "IMMEDIATE_LAND"


class GeofenceBreachAction(str, Enum):
    RETURN_TO_HOME = "RETURN_TO_HOME"
    IMMEDIATE_LAND = "IMMEDIATE_LAND"


class UserRole(str, Enum):
    PRODUCTION_PLANNER = "ProductionPlanner"
    AUTHORITY_OFFICER = "AuthorityOfficer"
    SAFETY_OFFICER = "SafetyOfficer"
    FLEET_MANAGER = "FleetManager"
    OPS_ADMIN = "OpsAdmin"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Site(TypedDict):
    id: str
    name: str
    latitude: float
    longitude: float
    ground_length_m: float
    ground_width_m: float
    site_max_wind_kt: float
    site_max_gust_kt: float
    site_max_altitude_ft: float
    created_at: str
    updated_at: str
    version: int


class ShowEvent(TypedDict):
    id: str
    site_id: str
    name: str
    window_start: str
    window_end: str
    drone_count_planned: int
    backup_window_start: Optional[str]
    backup_window_end: Optional[str]
    backup_consumed: bool
    lifecycle_status: str
    payment_status: str
    contract_value_cents: int
    deposit_cents: int
    balance_cents: int
    paid_total_cents: int
    refunded_total_cents: int
    cancellation_status: str
    cancelled_at: Optional[str]
    cancellation_tier: Optional[str]
    refund_due_cents: Optional[int]
    pinned_design_id: Optional[str]
    pinned_safety_config_id: Optional[str]
    pinned_authorization_id: Optional[str]
    assigned_count: int
    readiness_posture: str
    created_at: str
    updated_at: str
    version: int


class AirspaceAuthorization(TypedDict):
    id: str
    show_event_id: str
    window_start: str
    window_end: str
    altitude_ceiling_ft: float
    waiver_types: List[str]
    status: str
    decided_at: Optional[str]
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShowDesign(TypedDict):
    id: str
    show_event_id: str
    design_version_no: int
    drone_count: int
    max_altitude_ft: float
    duration_sec: int
    min_separation_m: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SimulationRun(TypedDict):
    # Immutable telemetry: id + created_at only (no updated_at, no version).
    id: str
    show_design_id: str
    min_separation_observed_m: float
    battery_draw_pct: float
    max_speed_mps: float
    verdict: str
    created_at: str


class SafetyConfiguration(TypedDict):
    id: str
    show_event_id: str
    geofence_radius_m: float
    altitude_hard_ceiling_ft: float
    lost_link_action: str
    geofence_breach_action: str
    battery_rtl_threshold_pct: int
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Drone(TypedDict):
    id: str
    serial_number: str
    model: str
    charge_pct: int
    battery_cycle_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChargeBay(TypedDict):
    id: str
    site_id: str
    bay_code: str
    port_count: int
    created_at: str
    updated_at: str
    version: int


class ChargeSession(TypedDict):
    id: str
    drone_id: str
    charge_bay_id: str
    charge_from_pct: int
    charge_to_pct: Optional[int]
    started_at: str
    ended_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LaunchGridAssignment(TypedDict):
    id: str
    show_event_id: str
    drone_id: str
    grid_row: int
    grid_col: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WeatherReading(TypedDict):
    # Immutable telemetry: id + created_at only (no updated_at, no version).
    id: str
    site_id: str
    recorded_at: str
    wind_speed_kt: float
    gust_kt: float
    precip_mm_hr: float
    temperature_c: float
    created_at: str


class GoNoGoEvaluation(TypedDict):
    id: str
    show_event_id: str
    evaluated_at: str
    verdict: str
    reason_codes: List[str]
    effective_wind_limit_kt: float
    effective_gust_limit_kt: float
    status: str
    certified_at: Optional[str]
    certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    show_event_id: str
    drone_id: Optional[str]
    severity: str
    description: str
    source: str
    status: str
    filed_by_user_id: str
    closed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FlightLog(TypedDict):
    # Immutable telemetry: id + created_at only (no updated_at, no version).
    id: str
    show_event_id: str
    drone_id: str
    battery_consumed_pct: int
    max_altitude_reached_ft: float
    max_deviation_m: float
    flag_status: str
    created_at: str
