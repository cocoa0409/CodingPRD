"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    NETWORK_PLANNER = "NetworkPlanner"
    TEST_SUPERVISOR = "TestSupervisor"
    FIELD_TECHNICIAN = "FieldTechnician"
    SAFETY_OFFICER = "SafetyOfficer"
    FAULT_CREW_LEAD = "FaultCrewLead"
    DISPATCH_COORDINATOR = "DispatchCoordinator"
    ASSET_ENGINEER = "AssetEngineer"


class CircuitStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUTAGE_PENDING = "OUTAGE_PENDING"
    DE_ENERGIZED = "DE_ENERGIZED"
    GROUNDED = "GROUNDED"
    UNDER_TEST = "UNDER_TEST"
    TEST_COMPLETE = "TEST_COMPLETE"
    RESTORING = "RESTORING"


class WindowStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class WindowKind(str, Enum):
    PLANNED_DIAGNOSTIC = "PLANNED_DIAGNOSTIC"
    EMERGENCY_FAULT = "EMERGENCY_FAULT"
    REPAIR_RESTORE = "REPAIR_RESTORE"


class JobStatus(str, Enum):
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    EVALUATION = "EVALUATION"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class PermitStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    GROUNDING_VERIFIED = "GROUNDING_VERIFIED"
    RELEASED = "RELEASED"


class SeriesStatus(str, Enum):
    SETUP = "SETUP"
    ENERGIZING = "ENERGIZING"
    LOGGING = "LOGGING"
    EVALUATED = "EVALUATED"
    ACCEPTED = "ACCEPTED"
    INVALID = "INVALID"


class SeriesMethod(str, Enum):
    VLF_TAN_DELTA = "VLF_TAN_DELTA"
    VLF_WITH_PD = "VLF_WITH_PD"
    PD_MAPPING = "PD_MAPPING"


class Verdict(str, Enum):
    PASS = "PASS"
    MONITOR = "MONITOR"
    FAIL = "FAIL"


class FaultStatus(str, Enum):
    SUSPECTED = "SUSPECTED"
    PINPOINTED = "PINPOINTED"
    EXCAVATING = "EXCAVATING"
    REPAIRING = "REPAIRING"
    REPAIRED = "REPAIRED"
    RETESTING = "RETESTING"
    CLOSED_VERIFIED = "CLOSED_VERIFIED"
    REOPENED = "REOPENED"


class PinpointMethod(str, Enum):
    PULSE_ECHO = "PULSE_ECHO"
    ARC_REFLECTION = "ARC_REFLECTION"


class ExcavationStatus(str, Enum):
    DRAFT = "DRAFT"
    PERMITTED = "PERMITTED"
    IN_PROGRESS = "IN_PROGRESS"
    BACKFILLED = "BACKFILLED"
    CANCELLED = "CANCELLED"


class SpliceStatus(str, Enum):
    PLANNED = "PLANNED"
    SPLICING = "SPLICING"
    CURING = "CURING"
    COMPLETED = "COMPLETED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class SpliceType(str, Enum):
    HEAT_SHRINK = "HEAT_SHRINK"
    COLD_SHRINK = "COLD_SHRINK"
    PREMOLDED = "PREMOLDED"


class UnitStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    MAINTENANCE = "MAINTENANCE"


class UnitCapability(str, Enum):
    VLF = "VLF"
    PD = "PD"
    TDR = "TDR"


class AssignmentStatus(str, Enum):
    RESERVED = "RESERVED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class AssessmentStatus(str, Enum):
    COMPUTED = "COMPUTED"
    REVIEWED = "REVIEWED"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"


class AssessmentBasis(str, Enum):
    FORMAL = "FORMAL"
    PROVISIONAL = "PROVISIONAL"


class HealthBand(str, Enum):
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    CRITICAL = "CRITICAL"


class RecommendedAction(str, Enum):
    NONE = "NONE"
    MONITOR = "MONITOR"
    PLAN_REPLACEMENT = "PLAN_REPLACEMENT"
    URGENT_REPLACEMENT = "URGENT_REPLACEMENT"


class VoltageClass(str, Enum):
    KV_15 = "KV_15"
    KV_25 = "KV_25"
    KV_35 = "KV_35"
    KV_69 = "KV_69"


# --- Entity TypedDicts ---
# All entities except TestReading carry id + created_at + updated_at + version
# (PRD §2.5). TestReading is the append-only exception: only id + created_at.


class CableCircuit(TypedDict, total=False):
    id: str
    circuit_ref: str
    voltage_class: str
    length_m: int
    installation_year: int
    calibrated_velocity_factor: Optional[float]
    status: str
    unresolved_fault_count: int
    resolved_fault_count_24m: int
    current_health_index: Optional[float]
    current_health_band: Optional[str]
    replacement_recommended: bool
    approved_outage_minutes_total: int
    splice_count: int
    created_at: str
    updated_at: str
    version: int


class OutageWindow(TypedDict, total=False):
    id: str
    circuit_id: str
    kind: str
    window_start: str
    window_end: str
    status: str
    duration_minutes: int
    restored_at: Optional[str]
    overrun_minutes: int
    overrun_charge_cents: int
    estimated_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class TestJob(TypedDict, total=False):
    id: str
    circuit_id: str
    outage_window_id: str
    requested_methods: List[str]
    approved_budget_cents: int
    use_temperature_correction: bool
    estimate_cents: Optional[int]
    committed_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IsolationPermit(TypedDict, total=False):
    id: str
    test_job_id: str
    isolation_points: List[str]
    ground_count: int
    status: str
    issued_by_user_id: Optional[str]
    grounding_verified_by_user_id: Optional[str]
    released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TestSeries(TypedDict, total=False):
    id: str
    test_job_id: str
    method: str
    test_voltage_kv: float
    is_retest: bool
    retest_of_fault_id: Optional[str]
    step_count: int
    status: str
    verdict_as_tested: Optional[str]
    verdict_temperature_corrected: Optional[str]
    verdict: Optional[str]
    max_tan_delta_e3: Optional[float]
    max_pd_pc: Optional[float]
    created_at: str
    updated_at: str
    version: int


class TestReading(TypedDict, total=False):
    # Append-only log entry: carries ONLY id + created_at plus its own fields.
    # NO updated_at, NO version (PRD §2.5).
    id: str
    test_series_id: str
    step_index: int
    applied_voltage_kv: float
    tan_delta_e3: Optional[float]
    pd_level_pc: Optional[float]
    pd_location_m: Optional[float]
    ambient_temp_c: float
    recorded_by_user_id: str
    created_at: str


class FaultRecord(TypedDict, total=False):
    id: str
    test_job_id: str
    test_series_id: str
    status: str
    pinpoint_method: Optional[str]
    trace_time_us: Optional[float]
    velocity_factor_used: Optional[float]
    pinpointed_distance_m: Optional[float]
    alternate_distance_m: Optional[float]
    corridor_start_m: Optional[float]
    corridor_end_m: Optional[float]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExcavationOrder(TypedDict, total=False):
    id: str
    fault_record_id: str
    target_location_m: float
    dig_start: str
    dig_end: str
    permit_ref: str
    cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairSplice(TypedDict, total=False):
    id: str
    fault_record_id: str
    excavation_order_id: str
    splice_type: str
    cost_cents: int
    status: str
    cure_started_at: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MobileUnit(TypedDict, total=False):
    id: str
    unit_code: str
    capabilities: List[str]
    max_test_voltage_kv: float
    status: str
    committed_hours: float
    created_at: str
    updated_at: str
    version: int


class EquipmentAssignment(TypedDict, total=False):
    id: str
    mobile_unit_id: str
    test_job_id: str
    mobilize_at: str
    demobilize_at: str
    duration_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class HealthAssessment(TypedDict, total=False):
    id: str
    circuit_id: str
    basis: str
    supersedes_id: Optional[str]
    health_index_score: float
    band: str
    recommended_action: str
    penalty_components: dict
    status: str
    created_at: str
    updated_at: str
    version: int
