"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    INTEGRITY_ANALYST = "IntegrityAnalyst"
    FIELD_TECHNICIAN = "FieldTechnician"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    DISPATCH_COORDINATOR = "DispatchCoordinator"
    CALIBRATION_TECH = "CalibrationTech"


class PipeSegmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    ABANDONED = "ABANDONED"


class SegmentPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class Material(str, Enum):
    STEEL = "STEEL"
    CAST_IRON = "CAST_IRON"
    PLASTIC_PE = "PLASTIC_PE"
    PLASTIC_PVC = "PLASTIC_PVC"
    COPPER = "COPPER"


class PressureClass(str, Enum):
    DISTRIBUTION = "DISTRIBUTION"
    TRANSMISSION = "TRANSMISSION"
    SERVICE = "SERVICE"


class InstrumentType(str, Enum):
    FLAME_IONIZATION = "FLAME_IONIZATION"
    CGI = "CGI"
    OMD = "OMD"
    AERIAL_LIDAR = "AERIAL_LIDAR"
    CP_VOLTMETER = "CP_VOLTMETER"


class InstrumentStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_CALIBRATION = "OUT_OF_CALIBRATION"
    RETIRED = "RETIRED"


class CalibrationOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SurveyMethod(str, Enum):
    WALKING = "WALKING"
    MOBILE = "MOBILE"
    AERIAL = "AERIAL"
    PATROL = "PATROL"


class SurveyRouteStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class AssignmentStatus(str, Enum):
    PENDING = "PENDING"
    COVERED = "COVERED"
    SKIPPED = "SKIPPED"


class SurveyRunStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class LeakGrade(str, Enum):
    G1 = "G1"
    G2 = "G2"
    G3 = "G3"


class LeakStatus(str, Enum):
    OPEN = "OPEN"
    REPAIR_SCHEDULED = "REPAIR_SCHEDULED"
    UNDER_REPAIR = "UNDER_REPAIR"
    REPAIRED_PENDING_VERIFICATION = "REPAIRED_PENDING_VERIFICATION"
    VERIFIED_CLEARED = "VERIFIED_CLEARED"
    ABANDONED_SEGMENT = "ABANDONED_SEGMENT"


class RepairMethod(str, Enum):
    CLAMP = "CLAMP"
    WRAP = "WRAP"
    CUT_AND_REPLACE = "CUT_AND_REPLACE"
    ABANDON_SEGMENT = "ABANDON_SEGMENT"
    INSERT_LINER = "INSERT_LINER"


class RepairPriority(str, Enum):
    P1_EMERGENCY = "P1_EMERGENCY"
    P2_URGENT = "P2_URGENT"
    P3_ROUTINE = "P3_ROUTINE"


class DispatchStatus(str, Enum):
    PENDING_DISPATCH = "PENDING_DISPATCH"
    DISPATCHED = "DISPATCHED"
    ON_SITE = "ON_SITE"
    WORK_COMPLETE = "WORK_COMPLETE"
    CANCELLED = "CANCELLED"


class ExcavationPermitTrack(str, Enum):
    """RepairOrder.excavation_permit_status parallel dimension."""

    NOT_REQUIRED = "NOT_REQUIRED"
    PERMIT_REQUIRED = "PERMIT_REQUIRED"
    PERMIT_APPLIED = "PERMIT_APPLIED"
    PERMIT_GRANTED = "PERMIT_GRANTED"
    PERMIT_DENIED = "PERMIT_DENIED"
    PERMIT_EXPIRED = "PERMIT_EXPIRED"


class PermitStatus(str, Enum):
    APPLIED = "APPLIED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    AT_CAPACITY = "AT_CAPACITY"
    OFF_DUTY = "OFF_DUTY"


class AnomalyStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class Regulator(str, Enum):
    PHMSA = "PHMSA"
    STATE_PUC = "STATE_PUC"
    LOCAL_FIRE_MARSHAL = "LOCAL_FIRE_MARSHAL"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED_BY_REGULATOR = "REJECTED_BY_REGULATOR"
    RESUBMISSION_REQUIRED = "RESUBMISSION_REQUIRED"


class SnapshotKind(str, Enum):
    LEAK_SECTION = "LEAK_SECTION"
    CP_SECTION = "CP_SECTION"
    FULL = "FULL"


class SnapshotStatus(str, Enum):
    STALE = "STALE"
    CURRENT = "CURRENT"
    PINNED = "PINNED"


class PersonnelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


# --- Entity TypedDicts (all entities carry id + created_at + updated_at + version) ---


class PipeSegment(TypedDict, total=False):
    id: str
    segment_code: str
    install_year: int
    material: str
    diameter_inches: float
    length_feet: float
    operating_pressure_psi: float
    pressure_class: str
    is_high_consequence_area: bool
    region_hint: Optional[str]
    risk_score: float
    open_grade1_count: int
    open_grade2_count: int
    open_grade3_count: int
    posture: str
    last_surveyed_at: Optional[str]
    next_survey_due_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Instrument(TypedDict, total=False):
    id: str
    serial_number: str
    instrument_type: str
    calibrated_at: Optional[str]
    calibration_due_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Calibration(TypedDict, total=False):
    id: str
    instrument_id: str
    performed_by_user_id: str
    reference_gas_ppm: float
    observed_ppm: float
    drift_pct: float
    outcome: str
    created_at: str
    updated_at: str
    version: int


class SurveyRoute(TypedDict, total=False):
    id: str
    route_code: str
    survey_method: str
    scheduled_window_start: str
    scheduled_window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RouteSegmentAssignment(TypedDict, total=False):
    id: str
    route_id: str
    segment_id: str
    sequence_index: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveyRun(TypedDict, total=False):
    id: str
    route_id: str
    instrument_id: str
    technician_id: str
    started_at: str
    ended_at: Optional[str]
    distance_covered_feet: float
    coverage_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Leak(TypedDict, total=False):
    id: str
    segment_id: str
    survey_run_id: str
    discovered_at: str
    concentration_ppm: float
    distance_to_building_feet: Optional[float]
    bar_hole_reading_pct_lel: float
    is_migration_evidence: bool
    grade: str
    repair_due_at: str
    regrade_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairOrder(TypedDict, total=False):
    id: str
    leak_id: str
    priority: str
    crew_id: Optional[str]
    dispatched_at: Optional[str]
    repair_method: str
    dispatch_status: str
    excavation_permit_status: str
    completed_at: Optional[str]
    verified_by_officer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExcavationPermit(TypedDict, total=False):
    id: str
    repair_order_id: str
    permit_number: str
    jurisdiction: str
    applied_at: str
    granted_at: Optional[str]
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RepairCrew(TypedDict, total=False):
    id: str
    crew_code: str
    home_region: str
    is_qualified_excavation: bool
    max_concurrent_orders: int
    open_order_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CathodicProtectionReading(TypedDict, total=False):
    id: str
    segment_id: str
    test_point_id: str
    recorded_at: str
    pipe_to_soil_potential_mv: float
    instant_off_potential_mv: float
    is_anomalous: bool
    anomaly_status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceReport(TypedDict, total=False):
    id: str
    reporting_period_start: str
    reporting_period_end: str
    regulator: str
    report_payload_uri: Optional[str]
    leak_section_snapshot_id: Optional[str]
    cp_section_snapshot_id: Optional[str]
    submitted_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class RiskModelSnapshot(TypedDict, total=False):
    id: str
    snapshot_label: str
    snapshot_kind: str
    input_set_hash: str
    total_segments_scored: int
    high_risk_segment_ids: List[str]
    generated_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RegradeEvent(TypedDict, total=False):
    id: str
    leak_id: str
    previous_grade: str
    new_grade: str
    reason: str
    performed_by_user_id: str
    triggered_at: str
    created_at: str
    updated_at: str
    version: int


class FieldTechnician(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    qualified_methods: List[str]
    home_region: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceOfficer(TypedDict, total=False):
    id: str
    employee_code: str
    full_name: str
    jurisdiction_scope: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PersonnelRecord(TypedDict, total=False):
    """CalibrationTech / DispatchCoordinator / IntegrityAnalyst share this shape."""

    id: str
    employee_code: str
    full_name: str
    status: str
    created_at: str
    updated_at: str
    version: int
