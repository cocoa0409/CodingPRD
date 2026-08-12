"""Domain types: entity TypedDicts, status enums, role enum (construction materials testing PRD)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    AGENCY_ADMIN = "AgencyAdmin"
    PROJECT_MANAGER = "ProjectManager"
    ENGINEER_OF_RECORD = "EngineerOfRecord"
    TECHNICIAN = "Technician"
    LAB_ANALYST = "LabAnalyst"
    CONTRACTOR = "Contractor"
    BUILDING_OFFICIAL = "BuildingOfficial"


class TestMethod(str, Enum):
    CONCRETE_STRENGTH = "CONCRETE_STRENGTH"
    SOIL_COMPACTION = "SOIL_COMPACTION"
    WELD_VISUAL = "WELD_VISUAL"
    BOLT_TENSION = "BOLT_TENSION"


class ProctorMethod(str, Enum):
    STANDARD = "STANDARD"
    MODIFIED = "MODIFIED"


class AcceptanceMethod(str, Enum):
    MOVING_AVERAGE = "MOVING_AVERAGE"
    INDIVIDUAL_SET = "INDIVIDUAL_SET"


class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class CompliancePosture(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    NONCONFORMANCE_OUTSTANDING = "NONCONFORMANCE_OUTSTANDING"
    READY_FOR_LETTER = "READY_FOR_LETTER"
    LETTER_ISSUED = "LETTER_ISSUED"


class LetterStatus(str, Enum):
    NONE = "NONE"
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class SSIRevisionStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class ScopeItemStatus(str, Enum):
    OPEN = "OPEN"
    SATISFIED = "SATISFIED"


class TechnicianStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AssignmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class FieldTestStatus(str, Enum):
    RECORDED = "RECORDED"
    VOIDED = "VOIDED"


class TestResult(str, Enum):
    CONFORMING = "CONFORMING"
    NONCONFORMING = "NONCONFORMING"


class LabSampleStatus(str, Enum):
    CAST = "CAST"
    BREAK_SCHEDULED = "BREAK_SCHEDULED"
    REPORTED = "REPORTED"
    DISCARDED = "DISCARDED"


class NcrStatus(str, Enum):
    OPEN = "OPEN"
    CORRECTION_SUBMITTED = "CORRECTION_SUBMITTED"
    ESCALATED = "ESCALATED"
    VERIFIED = "VERIFIED"


class NcrSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    STRUCTURAL = "STRUCTURAL"


class NcrSourceType(str, Enum):
    FIELD_TEST = "FIELD_TEST"
    LAB_SAMPLE = "LAB_SAMPLE"


class DailyReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class DiscrepancyStatus(str, Enum):
    RAISED = "RAISED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    RESOLVED = "RESOLVED"


class DiscrepancyRoute(str, Enum):
    CONTRACTOR = "CONTRACTOR"
    ENGINEER = "ENGINEER"


class Certification(TypedDict):
    method: str
    level: int
    expires_at: str


# All entities carry the common fields id / created_at / updated_at / version.

class Project(TypedDict):
    id: str
    name: str
    permit_number: str
    jurisdiction: str
    contractor_name: str
    building_official_name: str
    status: str
    compliance_posture: str
    open_ncr_count: int
    current_approved_ssi_id: Optional[str]
    letter_status: str
    letter_issued_at: Optional[str]
    letter_issued_by: Optional[str]
    letter_void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SSIRevision(TypedDict):
    id: str
    project_id: str
    revision_number: int
    specified_fc_psi: int
    acceptance_method_concrete: str
    status: str
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScopeItem(TypedDict):
    id: str
    ssi_revision_id: str
    test_method: str
    description: str
    required_cert_level: int
    required_count: int
    is_structural: bool
    proctor_method: str
    standard_max_density_pcf: Optional[float]
    modified_max_density_pcf: Optional[float]
    completed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Technician(TypedDict):
    id: str
    full_name: str
    employee_code: str
    certifications: List[Certification]
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionAssignment(TypedDict):
    id: str
    project_id: str
    scope_item_id: str
    technician_id: str
    ssi_revision_id: str
    work_date: str
    start_time: str
    end_time: str
    status: str
    completion_note: Optional[str]
    completed_at: Optional[str]
    covered_by_dir_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FieldTest(TypedDict):
    id: str
    assignment_id: str
    measured_values: dict
    test_method: str
    technician_id: str
    project_id: str
    result: str
    result_details: dict
    status: str
    created_at: str
    updated_at: str
    version: int


class LabSample(TypedDict):
    id: str
    assignment_id: str
    lab_id: str
    cast_at: str
    required_break_age_days: int
    break_due_at: str
    break_scheduled_date: Optional[str]
    broken_at: Optional[str]
    cylinder_strengths_psi: Optional[List[float]]
    set_average_psi: Optional[int]
    age_at_break_hours: Optional[int]
    within_tolerance: Optional[bool]
    flagged_out_of_tolerance: Optional[bool]
    break_result: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lab(TypedDict):
    id: str
    name: str
    lab_code: str
    daily_break_capacity: int
    created_at: str
    updated_at: str
    version: int


class NonconformanceReport(TypedDict):
    id: str
    project_id: str
    ncr_number: str
    source_type: str
    source_id: str
    scope_item_id: str
    description: str
    severity: str
    detected_at: str
    deadline_date: str
    rejection_count: int
    correction_note: Optional[str]
    verified_by_technician_id: Optional[str]
    evidence_field_test_id: Optional[str]
    escalation_score: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DailyInspectionReport(TypedDict):
    id: str
    project_id: str
    technician_id: str
    report_date: str
    assignment_ids: List[str]
    summary: str
    status: str
    acknowledged_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DiscrepancyTicket(TypedDict):
    id: str
    project_id: str
    scope_item_id: Optional[str]
    raised_by_technician_id: str
    subject: str
    description: str
    routed_to: str
    response_text: Optional[str]
    round_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
