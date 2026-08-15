"""Domain types: entity TypedDicts, status enums, role enum (PRD §2/§3/§4)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class Posture(str, Enum):
    NORMAL = "NORMAL"
    DEGRADED = "DEGRADED"
    EMERGENCY = "EMERGENCY"
    FROZEN = "FROZEN"


class PumpStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    STANDBY = "STANDBY"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    REBUILD = "REBUILD"


class AlarmClass(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"


class AlarmTicketStatus(str, Enum):
    OPEN = "OPEN"
    ACKED = "ACKED"
    DISPATCHED = "DISPATCHED"
    ON_SCENE = "ON_SCENE"
    CLEARED = "CLEARED"
    CANCELLED = "CANCELLED"


class ReadingSource(str, Enum):
    SCADA = "SCADA"
    MANUAL = "MANUAL"
    BACKFILL = "BACKFILL"


class RebuildStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CleaningStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    OVERDUE = "OVERDUE"


class GeneratorTestKind(str, Enum):
    NO_LOAD = "NO_LOAD"
    LOAD_BANK = "LOAD_BANK"
    TRANSFER_SWITCH = "TRANSFER_SWITCH"


class GeneratorTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    ABORTED = "ABORTED"
    OVERDUE = "OVERDUE"


class SsoStatus(str, Enum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    REPORT_DRAFT = "REPORT_DRAFT"
    REPORT_SUBMITTED = "REPORT_SUBMITTED"
    REPORT_ACCEPTED = "REPORT_ACCEPTED"
    CLOSED = "CLOSED"


class SsoCauseCode(str, Enum):
    GREASE_BLOCKAGE = "GREASE_BLOCKAGE"
    DEBRIS = "DEBRIS"
    POWER_FAILURE = "POWER_FAILURE"
    PUMP_FAILURE = "PUMP_FAILURE"
    INFLOW_INFILTRATION = "INFLOW_INFILTRATION"
    VANDALISM = "VANDALISM"
    UNKNOWN = "UNKNOWN"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class CapitalPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    RANKED = "RANKED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"


class CapitalProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    RANKED = "RANKED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    CANCELLED = "CANCELLED"


class SparePumpStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    DEPLOYED = "DEPLOYED"
    REBUILD = "REBUILD"
    RETIRED = "RETIRED"


class Certification(str, Enum):
    CSE_1 = "CSE_1"
    CSE_2 = "CSE_2"
    ELEC_1 = "ELEC_1"
    GEN_OP = "GEN_OP"
    COLLECTIONS_2 = "COLLECTIONS_2"


class UserRole(str, Enum):
    UTILITY_ADMIN = "UtilityAdmin"
    OPERATIONS_SUPERVISOR = "OperationsSupervisor"
    ON_CALL_OPERATOR = "OnCallOperator"
    OPERATOR = "Operator"
    MAINTENANCE_PLANNER = "MaintenancePlanner"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CAPITAL_PROGRAM_MANAGER = "CapitalProgramManager"
    SCADA_WEBHOOK = "ScadaWebhook"
    REGULATOR_PORTAL = "RegulatorPortal"


class LiftStation(TypedDict, total=False):
    id: str
    station_code: str
    service_zone: str
    design_capacity_gpm: int
    pump_count: int
    has_backup_generator: bool
    wet_well_volume_gal: int
    operational_posture: str
    firm_capacity_available_gpm: int
    last_sso_occurred_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Pump(TypedDict, total=False):
    id: str
    station_id: str
    position_index: int
    rated_gpm: int
    status: str
    cumulative_runtime_hours: float
    runtime_since_rebuild_hours: float
    last_alternation_at: Optional[str]
    rebuild_count: int
    created_at: str
    updated_at: str
    version: int


class RuntimeReading(TypedDict, total=False):
    # Append-only telemetry stream: carries only id + created_at (PRD §2.4);
    # updated_at and version are absent by design.
    id: str
    pump_id: str
    recorded_at: str
    run_hours_delta: float
    starts_count: int
    source: str
    created_at: str


class AlarmTicket(TypedDict, total=False):
    id: str
    station_id: str
    alarm_class: str
    alarm_code: str
    raised_at: str
    status: str
    assigned_operator_id: Optional[str]
    acked_at: Optional[str]
    dispatched_at: Optional[str]
    cleared_at: Optional[str]
    response_minutes: Optional[int]
    is_sso_related: bool
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    certifications: List[str]
    home_zone: str
    is_active: bool
    active_ticket_count: int
    consecutive_callouts_24h: int
    created_at: str
    updated_at: str
    version: int


class PumpRebuild(TypedDict, total=False):
    id: str
    pump_id: str
    work_order_ref: str
    started_at: str
    completed_at: Optional[str]
    status: str
    cost_usd: float
    pre_rebuild_runtime_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


class WetWellCleaning(TypedDict, total=False):
    id: str
    station_id: str
    scheduled_for: str
    status: str
    completed_at: Optional[str]
    grease_depth_inches_pre: float
    grease_depth_inches_post: Optional[float]
    crew_lead_operator_id: str
    requires_confined_space_entry: bool
    created_at: str
    updated_at: str
    version: int


class GeneratorTest(TypedDict, total=False):
    id: str
    station_id: str
    scheduled_for: str
    test_kind: str
    status: str
    started_at: Optional[str]
    duration_minutes: Optional[int]
    load_percent: float
    outcome_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SsoEvent(TypedDict, total=False):
    id: str
    station_id: str
    started_at: str
    stopped_at: Optional[str]
    estimated_volume_gal: Optional[float]
    cause_code: str
    status: str
    regulator_deadline_at: Optional[str]
    report_submitted_at: Optional[str]
    report_accepted_at: Optional[str]
    reached_surface_water: bool
    created_at: str
    updated_at: str
    version: int


class ConfinedSpacePermit(TypedDict, total=False):
    id: str
    station_id: str
    work_description: str
    authorized_entrant_id: str
    attendant_operator_id: str
    entry_supervisor_id: str
    status: str
    issued_at: Optional[str]
    valid_until: Optional[str]
    closed_at: Optional[str]
    gas_test_passed: bool
    created_at: str
    updated_at: str
    version: int


class CapitalPlan(TypedDict, total=False):
    id: str
    plan_year: int
    status: str
    budget_total_usd: float
    budget_allocated_usd: float
    budget_remaining_usd: float
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CapitalProject(TypedDict, total=False):
    id: str
    plan_id: str
    station_id: str
    project_name: str
    estimated_cost_usd: float
    risk_score: float
    priority_rank: Optional[int]
    status: str
    consequence_of_failure: int
    likelihood_of_failure: int
    created_at: str
    updated_at: str
    version: int


class SparePump(TypedDict, total=False):
    id: str
    asset_tag: str
    rated_gpm: int
    compatible_zone: str
    status: str
    reserved_for_station_id: Optional[str]
    deployed_at_station_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
