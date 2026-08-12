"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class ArffIndex(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"
    NONE = "NONE"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    DOWNGRADED = "DOWNGRADED"
    NONCOMPLIANT = "NONCOMPLIANT"


class VehicleStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class ReadinessResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NONE = "NONE"


class FirefighterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class DrillStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    CERTIFIED = "CERTIFIED"
    FAILED = "FAILED"


class DrillOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DeterminationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class AlertLevel(str, Enum):
    ALERT_1 = "ALERT_1"
    ALERT_2 = "ALERT_2"
    ALERT_3 = "ALERT_3"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    RESPONDING = "RESPONDING"
    CONTROLLED = "CONTROLLED"
    CLOSED = "CLOSED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class RequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DEPLOYED = "DEPLOYED"
    RELEASED = "RELEASED"
    DECLINED = "DECLINED"


class OosEventStatus(str, Enum):
    OPEN = "OPEN"
    RESTORED = "RESTORED"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"
    OVERDUE = "OVERDUE"


class NotificationCause(str, Enum):
    EQUIPMENT = "EQUIPMENT"
    STAFFING = "STAFFING"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_FAIL = "CLOSED_FAIL"


class DrillType(str, Enum):
    AIRCRAFT = "AIRCRAFT"
    STRUCTURAL = "STRUCTURAL"


class TrainingResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class UserRole(str, Enum):
    AIRPORT_MANAGER = "AirportManager"
    ARFF_CHIEF = "ArffChief"
    SAFETY_OFFICER = "SafetyOfficer"
    FAA_INSPECTOR = "FaaInspector"
    FIREFIGHTER = "Firefighter"


class AirportOpsProfile(TypedDict):
    id: str
    airport_code: str
    certificated_index: str
    required_index_by_aircraft: str
    supported_index_by_equipment: str
    supported_index_by_staffing: str
    effective_index: str
    index_compliance_status: str
    created_at: str
    updated_at: str
    version: int


class AircraftType(TypedDict):
    id: str
    model_name: str
    length_ft: float
    avg_daily_departures: float
    in_scheduled_service: bool
    qualifies_for_index: bool
    index_band: str
    created_at: str
    updated_at: str
    version: int


class ArffVehicle(TypedDict):
    id: str
    call_sign: str
    water_capacity_gal: float
    dry_chem_capacity_lb: float
    status: str
    latest_readiness_result: str
    open_oos_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReadinessCheck(TypedDict):
    id: str
    vehicle_id: str
    water_available_gal: float
    dry_chem_available_lb: float
    discharge_system_ok: bool
    checked_at: str
    result: str
    created_at: str
    updated_at: str
    version: int


class Firefighter(TypedDict):
    id: str
    employee_no: str
    full_name: str
    status: str
    last_live_fire_completed_on: Optional[str]
    is_training_current: bool
    is_deployable: bool
    created_at: str
    updated_at: str
    version: int


class LiveFireTrainingRecord(TypedDict):
    id: str
    firefighter_id: str
    completed_on: str
    drill_type: str
    result: str
    created_at: str
    updated_at: str
    version: int


class ResponseDrill(TypedDict):
    id: str
    runway_designator: str
    scheduled_start: str
    scheduled_end: str
    first_vehicle_arrival_seconds: Optional[int]
    all_vehicles_arrival_seconds: Optional[int]
    executed_at: Optional[str]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IndexDetermination(TypedDict):
    id: str
    largest_aircraft_id: str
    new_certificated_index: str
    required_index: str
    vehicle_requirement_met: bool
    staffing_requirement_met: bool
    supersedes_determination_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AlertIncident(TypedDict):
    id: str
    alert_level: str
    aircraft_id: Optional[str]
    location: str
    reported_at: str
    controlled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MutualAidAgreement(TypedDict):
    id: str
    partner_airport_code: str
    max_alert_level: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MutualAidRequest(TypedDict):
    id: str
    incident_id: str
    agreement_id: str
    units_requested: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutOfServiceEvent(TypedDict):
    id: str
    vehicle_id: str
    reason: str
    started_at: str
    restored_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IndexDowngradeNotification(TypedDict):
    id: str
    prior_index: str
    downgraded_index: str
    cause: str
    notified_at: str
    cure_deadline: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AgentExpenditureLine(TypedDict):
    vehicle_id: str
    water_gal_used: float
    dry_chem_lb_used: float


class IncidentReport(TypedDict):
    id: str
    incident_id: str
    author_user_id: str
    narrative: str
    agent_expenditure_lines: list
    agent_expense_total_cents: int
    review_cycle_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PostIncidentReview(TypedDict):
    id: str
    incident_report_id: str
    findings: str
    corrective_actions_open: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FaaInspection(TypedDict):
    id: str
    inspection_year: int
    scheduled_on: str
    findings_count: Optional[int]
    concluded_outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
