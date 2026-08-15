"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's resource descriptions (section 3). Entities with
full mutable-resource semantics carry id + created_at + updated_at + version;
the append-only charge ledger entry carries only id + created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Status / enum vocabularies
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    FACILITY_ADMIN = "FacilityAdmin"
    PS_COORDINATOR = "PsCoordinator"
    MAINTENANCE_LEAD = "MaintenanceLead"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    OPERATOR = "Operator"
    CONTRACTOR_REP = "ContractorRep"


class ChargePosture(str, Enum):
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    AT_OR_ABOVE_THRESHOLD = "AT_OR_ABOVE_THRESHOLD"


class PsmProgramStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEGRADED = "DEGRADED"
    NONCOMPLIANT = "NONCOMPLIANT"


class SystemStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class EquipmentType(str, Enum):
    VESSEL = "VESSEL"
    COMPRESSOR = "COMPRESSOR"
    PIPING_CIRCUIT = "PIPING_CIRCUIT"
    PRV = "PRV"


class InspectionMethod(str, Enum):
    FIXED = "FIXED"
    CONDITION_BASED = "CONDITION_BASED"


class InspectionResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class IntegrityStatus(str, Enum):
    CURRENT = "CURRENT"
    DUE_SOON = "DUE_SOON"
    OVERDUE = "OVERDUE"
    FAILED = "FAILED"


class PsidDocType(str, Enum):
    PID = "PID"
    PSV_CALC = "PSV_CALC"
    RELIEF_DESIGN = "RELIEF_DESIGN"


class PsidDocStatus(str, Enum):
    CURRENT = "CURRENT"
    UNDER_REVIEW = "UNDER_REVIEW"
    SUPERSEDED = "SUPERSEDED"


class AdjustmentType(str, Enum):
    ADD = "ADD"
    REMOVE = "REMOVE"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OVERDUE = "OVERDUE"
    COMPLETED = "COMPLETED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class TrainingTopic(str, Enum):
    PSM_OVERVIEW = "PSM_OVERVIEW"
    AMMONIA_OPERATOR = "AMMONIA_OPERATOR"
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"


class TrainingCurrency(str, Enum):
    CURRENT = "CURRENT"
    EXPIRING_SOON = "EXPIRING_SOON"
    EXPIRED = "EXPIRED"


class DrillType(str, Enum):
    TABLETOP = "TABLETOP"
    FIELD = "FIELD"
    EVACUATION = "EVACUATION"


class DrillStatus(str, Enum):
    PLANNED = "PLANNED"
    CONDUCTED = "CONDUCTED"


class IncidentSeverity(str, Enum):
    NEAR_MISS = "NEAR_MISS"
    RECORDABLE = "RECORDABLE"
    REPORTABLE = "REPORTABLE"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    ACTIONS_ASSIGNED = "ACTIONS_ASSIGNED"
    CLOSED = "CLOSED"
    REOPENED = "REOPENED"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"


class AuditOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_THRESHOLD = "AUTO_THRESHOLD"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLOSED = "CLOSED"


class QualificationStatus(str, Enum):
    PENDING = "PENDING"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class LeakStatus(str, Enum):
    SUSPECTED = "SUSPECTED"
    CONFIRMED = "CONFIRMED"
    FALSE_ALARM = "FALSE_ALARM"


class NotificationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    OVERDUE = "OVERDUE"
    NOTIFIED = "NOTIFIED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Facility(TypedDict, total=False):
    id: str
    name: str
    threshold_lbs: float
    total_charge_lbs: float
    charge_posture: str
    psm_program_status: str
    overdue_inspection_count: int
    open_incident_count: int
    expired_training_count: int
    posture_score: int
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class RefrigerationSystem(TypedDict, total=False):
    id: str
    facility_id: str
    name: str
    design_charge_lbs: float
    condenser_approach_f: float
    min_head_psig: float
    max_head_psig: float
    float_head_enabled: bool
    last_gauge_reading_lbs: Optional[float]
    last_gauge_reading_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Equipment(TypedDict, total=False):
    id: str
    system_id: str
    tag_number: str
    equipment_type: str
    inspection_interval_days: int
    inspection_method: str
    last_completed_at: Optional[str]
    last_result: Optional[str]
    next_due_at: Optional[str]
    integrity_status: str
    created_at: str
    updated_at: str
    version: int


class PsidDocument(TypedDict, total=False):
    id: str
    system_id: str
    doc_type: str
    revision_label: str
    content_uri: str
    status: str
    last_reaffirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChargeAdjustment(TypedDict, total=False):
    # Append-only ledger event: carries ONLY id + created_at as common fields.
    # updated_at and version are deliberately absent.
    id: str
    created_at: str
    facility_id: str
    system_id: Optional[str]
    adjustment_type: str
    quantity_lbs: float
    rounded_lbs: float
    reason: str
    posted_by_employee_id: str


class Inspection(TypedDict, total=False):
    id: str
    equipment_id: str
    due_at: str
    status: str
    result: Optional[str]
    findings: Optional[str]
    completed_at: Optional[str]
    completed_late: bool
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    facility_id: str
    full_name: str
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict, total=False):
    id: str
    employee_id: str
    topic: str
    completed_at: str
    expires_at: str
    currency: str
    created_at: str
    updated_at: str
    version: int


class DrillEvent(TypedDict, total=False):
    id: str
    facility_id: str
    drill_type: str
    scheduled_start_at: str
    scheduled_end_at: str
    status: str
    attendee_employee_ids: Optional[List[str]]
    conducted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    facility_id: str
    equipment_id: Optional[str]
    severity: str
    description: str
    reported_by_employee_id: Optional[str]
    investigator_employee_id: Optional[str]
    status: str
    pending_action_count: int
    reopen_count: int
    source_leak_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict, total=False):
    id: str
    incident_id: str
    description: str
    assignee_employee_id: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict, total=False):
    id: str
    facility_id: str
    scheduled_start_at: str
    due_at: str
    lead_auditor: str
    origin: str
    status: str
    findings_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict, total=False):
    id: str
    company_name: str
    safety_score: int
    qualification_status: str
    qualified_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HotWorkPermit(TypedDict, total=False):
    id: str
    facility_id: str
    system_id: str
    contractor_id: str
    work_description: str
    valid_from: str
    valid_until: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LeakEvent(TypedDict, total=False):
    id: str
    system_id: str
    estimated_release_lbs: float
    source_description: str
    status: str
    final_release_lbs: Optional[float]
    confirmed_at: Optional[str]
    notification_required: bool
    notification_deadline_at: Optional[str]
    notification_status: str
    notified_at: Optional[str]
    late_notification: bool
    auto_incident_id: Optional[str]
    created_at: str
    updated_at: str
    version: int
